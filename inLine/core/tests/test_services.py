from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import FilaPrato, Pedido, Prato, TMA
from core.services import (
    calculate_tma_per_prato,
    claim_ready_orders_for_print,
    create_order,
    finalize_prato,
    mark_ready_order_as_printed,
    registrar_retirada_total_pedido,
)


class ServiceLayerTests(TestCase):
    def setUp(self):
        self.prato = Prato.objects.create(
            nome="Pastel",
            preco=Decimal("12.50"),
            estoque=10,
        )
        self.prato_2 = Prato.objects.create(
            nome="Caldo",
            preco=Decimal("8.00"),
            estoque=6,
        )

    def test_create_order_creates_unitary_queue_and_decrements_stock(self):
        pedido = create_order(
            tipo=Pedido.Tipo.NORMAL,
            itens=[{"prato_id": str(self.prato.id), "quantidade": 3}],
        )

        self.prato.refresh_from_db()

        self.assertEqual(pedido.tipo, Pedido.Tipo.NORMAL)
        self.assertEqual(pedido.total, Decimal("37.50"))
        self.assertEqual(pedido.filas.count(), 3)
        self.assertEqual(self.prato.estoque, 7)

    def test_create_order_raises_when_stock_is_insufficient(self):
        with self.assertRaisesMessage(ValueError, "Estoque insuficiente"):
            create_order(
                tipo=Pedido.Tipo.NORMAL,
                itens=[{"prato_id": str(self.prato.id), "quantidade": 11}],
            )

    def test_create_order_merges_duplicate_prato_lines_before_consuming_stock(self):
        pedido = create_order(
            tipo=Pedido.Tipo.NORMAL,
            itens=[
                {"prato_id": str(self.prato.id), "quantidade": 2},
                {"prato_id": str(self.prato.id), "quantidade": 1},
                {"prato_id": str(self.prato_2.id), "quantidade": 2},
            ],
        )

        self.prato.refresh_from_db()
        self.prato_2.refresh_from_db()

        self.assertEqual(pedido.total, Decimal("53.50"))
        self.assertEqual(pedido.filas.filter(prato=self.prato).count(), 3)
        self.assertEqual(pedido.filas.filter(prato=self.prato_2).count(), 2)
        self.assertEqual(self.prato.estoque, 7)
        self.assertEqual(self.prato_2.estoque, 4)

    def test_finalize_prato_marks_parent_order_as_finalized_when_last_item_finishes(self):
        pedido = create_order(
            tipo=Pedido.Tipo.NORMAL,
            itens=[{"prato_id": str(self.prato.id), "quantidade": 1}],
        )
        fila = pedido.filas.get()
        pedido.status = Pedido.Status.PRODUCAO
        pedido.save(update_fields=["status"])

        item_finalizado = finalize_prato(fila.id)
        pedido.refresh_from_db()

        self.assertIsNotNone(item_finalizado)
        self.assertEqual(item_finalizado.status, FilaPrato.Status.FINALIZADO)
        self.assertIsNotNone(item_finalizado.started_at)
        self.assertIsNotNone(item_finalizado.finished_at)
        self.assertEqual(pedido.status, Pedido.Status.FINALIZADO)
        self.assertIsNone(pedido.ready_printed_at)

    def test_calculate_tma_per_prato_creates_metric_and_marks_processed_items(self):
        pedido = Pedido.objects.create(tipo=Pedido.Tipo.NORMAL, total=Decimal("25.00"))
        inicio = timezone.now() - timedelta(minutes=7)

        fila_1 = FilaPrato.objects.create(
            pedido=pedido,
            prato=self.prato,
            preco_unitario=self.prato.preco,
            status=FilaPrato.Status.FINALIZADO,
            started_at=inicio,
            finished_at=inicio + timedelta(minutes=5),
        )
        fila_2 = FilaPrato.objects.create(
            pedido=pedido,
            prato=self.prato,
            preco_unitario=self.prato.preco,
            status=FilaPrato.Status.FINALIZADO,
            started_at=inicio,
            finished_at=inicio + timedelta(minutes=7),
        )

        calculate_tma_per_prato()

        fila_1.refresh_from_db()
        fila_2.refresh_from_db()
        tma = TMA.objects.get(prato=self.prato)

        self.assertTrue(fila_1.usado_em_metrica)
        self.assertTrue(fila_2.usado_em_metrica)
        self.assertEqual(tma.ultimo_prato_id, fila_2.id)
        self.assertAlmostEqual(tma.valor_tma_seg, 360.0)

    def test_registrar_retirada_total_pedido_marks_order_and_items_as_retirado(self):
        pedido = Pedido.objects.create(
            tipo=Pedido.Tipo.NORMAL,
            status=Pedido.Status.FINALIZADO,
            total=Decimal("25.00"),
        )
        FilaPrato.objects.create(
            pedido=pedido,
            prato=self.prato,
            preco_unitario=self.prato.preco,
            status=FilaPrato.Status.FINALIZADO,
            started_at=timezone.now() - timedelta(minutes=5),
            finished_at=timezone.now(),
        )

        registrar_retirada_total_pedido(pedido.id)

        pedido.refresh_from_db()
        fila = pedido.filas.get()
        self.assertEqual(pedido.status, Pedido.Status.RETIRADO)
        self.assertEqual(fila.status, FilaPrato.Status.RETIRADO)
        self.assertIsNotNone(fila.delivered_at)

    def test_registrar_retirada_total_pedido_blocks_partial_orders(self):
        pedido = Pedido.objects.create(
            tipo=Pedido.Tipo.NORMAL,
            status=Pedido.Status.PRODUCAO,
            total=Decimal("25.00"),
        )
        FilaPrato.objects.create(
            pedido=pedido,
            prato=self.prato,
            preco_unitario=self.prato.preco,
            status=FilaPrato.Status.PENDENTE,
        )

        with self.assertRaises(ValidationError):
            registrar_retirada_total_pedido(pedido.id)

    def test_mark_ready_order_as_printed_sets_timestamp_once(self):
        pedido = Pedido.objects.create(
            tipo=Pedido.Tipo.NORMAL,
            status=Pedido.Status.FINALIZADO,
            total=Decimal("25.00"),
        )

        mark_ready_order_as_printed(pedido.id)
        pedido.refresh_from_db()
        primeira_marcacao = pedido.ready_printed_at

        self.assertIsNotNone(primeira_marcacao)

        mark_ready_order_as_printed(pedido.id)
        pedido.refresh_from_db()
        self.assertEqual(pedido.ready_printed_at, primeira_marcacao)

    def test_mark_ready_order_as_printed_also_allows_retirado_orders(self):
        pedido = Pedido.objects.create(
            tipo=Pedido.Tipo.NORMAL,
            status=Pedido.Status.RETIRADO,
            total=Decimal("25.00"),
        )

        mark_ready_order_as_printed(pedido.id)
        pedido.refresh_from_db()

        self.assertIsNotNone(pedido.ready_printed_at)

    def test_claim_ready_orders_for_print_hides_order_until_ack(self):
        pedido = Pedido.objects.create(
            tipo=Pedido.Tipo.NORMAL,
            status=Pedido.Status.FINALIZADO,
            total=Decimal("25.00"),
        )

        primeira_busca = claim_ready_orders_for_print()
        segunda_busca = claim_ready_orders_for_print()
        pedido.refresh_from_db()

        self.assertEqual([p.id for p in primeira_busca], [pedido.id])
        self.assertEqual(segunda_busca, [])
        self.assertIsNotNone(pedido.ready_print_claimed_at)
        self.assertIsNotNone(pedido.ready_print_claim_token)

    def test_claim_ready_orders_for_print_reclaims_stale_claim(self):
        pedido = Pedido.objects.create(
            tipo=Pedido.Tipo.NORMAL,
            status=Pedido.Status.FINALIZADO,
            total=Decimal("25.00"),
            ready_print_claimed_at=timezone.now() - timedelta(minutes=10),
        )

        pedidos = claim_ready_orders_for_print()
        pedido.refresh_from_db()

        self.assertEqual([p.id for p in pedidos], [pedido.id])
        self.assertIsNotNone(pedido.ready_print_claim_token)
