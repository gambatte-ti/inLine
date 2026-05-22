from datetime import date
from decimal import Decimal

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.models import FilaPrato, Pedido, Prato, TMA
from core.services import create_order


class BaseApiTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.prato = Prato.objects.create(
            nome="Pastel",
            preco=Decimal("10.00"),
            estoque=20,
        )
        self.prato_2 = Prato.objects.create(
            nome="Caldo",
            preco=Decimal("8.50"),
            estoque=15,
        )


class CardapioApiTests(BaseApiTestCase):
    def test_create_prato_api(self):
        response = self.client.post(
            "/api/v1/pratos/criar/",
            {"nome": "Suco", "preco": "7.00", "estoque": 30},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Prato.objects.filter(nome="Suco").exists())

    def test_list_pratos_api_returns_active_items(self):
        self.prato_2.ativo = False
        self.prato_2.save(update_fields=["ativo"])

        response = self.client.get("/api/v1/pratos/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["nome"], "Pastel")

    def test_update_prato_api(self):
        response = self.client.put(
            f"/api/v1/pratos/editar/{self.prato.id}/",
            {"nome": "Pastel Especial", "preco": "14.90", "estoque": 9},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.prato.refresh_from_db()
        self.assertEqual(self.prato.nome, "Pastel Especial")
        self.assertEqual(self.prato.preco, Decimal("14.90"))
        self.assertEqual(self.prato.estoque, 9)

    def test_tma_dashboard_api_uses_latest_metric(self):
        TMA.objects.create(prato=self.prato, valor_tma_seg=180, ultimo_prato_id=self.prato.id)

        response = self.client.get("/api/v1/metrica/tma-dashboard/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload[0]["prato_nome"], "Pastel")
        self.assertEqual(payload[0]["tma_minutos"], 3.0)


class OperacaoApiTests(BaseApiTestCase):
    def test_create_order_api_returns_ticket_payload(self):
        response = self.client.post(
            "/api/v1/pedidos/criar/",
            {
                "tipo": Pedido.Tipo.PREFERENCIAL,
                "itens": [
                    {"prato_id": str(self.prato.id), "quantidade": 2},
                    {"prato_id": str(self.prato_2.id), "quantidade": 1},
                ],
            },
            format="json",
        )

        body = response.json()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(body["tipo"], Pedido.Tipo.PREFERENCIAL)
        self.assertEqual(body["senha"], str(body["id"])[:4].upper())
        self.assertTrue(body["criado_em"])
        self.assertEqual(len(body["itens"]), 3)

    def test_atendimento_lista_get_groups_order_items(self):
        pedido = create_order(
            tipo=Pedido.Tipo.NORMAL,
            itens=[
                {"prato_id": str(self.prato.id), "quantidade": 2},
                {"prato_id": str(self.prato_2.id), "quantidade": 1},
            ],
        )

        response = self.client.get("/api/v1/atendimento/lista/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body[0]["id"], str(pedido.id))
        self.assertEqual(len(body[0]["itens"]), 2)

    def test_atendimento_post_moves_order_to_producao(self):
        pedido = create_order(
            tipo=Pedido.Tipo.NORMAL,
            itens=[{"prato_id": str(self.prato.id), "quantidade": 2}],
        )
        fila_ids = list(pedido.filas.values_list("id", flat=True))
        created_at_original = {
            str(fila.id): fila.created_at for fila in pedido.filas.all()
        }

        response = self.client.post(
            f"/api/v1/atendimento/lista/{pedido.id}/",
            {"acao": "PRODUCAO"},
            format="json",
        )

        pedido.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(pedido.status, Pedido.Status.PRODUCAO)
        self.assertEqual(
            pedido.filas.filter(status=FilaPrato.Status.PENDENTE).count(),
            2,
        )
        for fila in pedido.filas.filter(id__in=fila_ids):
            self.assertEqual(fila.created_at, created_at_original[str(fila.id)])
            self.assertIsNotNone(fila.released_to_production_at)

    def test_atendimento_post_can_cancel_order(self):
        pedido = create_order(
            tipo=Pedido.Tipo.NORMAL,
            itens=[{"prato_id": str(self.prato.id), "quantidade": 1}],
        )

        response = self.client.post(
            f"/api/v1/atendimento/lista/{pedido.id}/",
            {"acao": "CANCELAR"},
            format="json",
        )

        pedido.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(pedido.status, Pedido.Status.CANCELADO)
        self.assertEqual(
            pedido.filas.filter(status=FilaPrato.Status.CANCELADO).count(),
            1,
        )

    def test_painel_cozinha_only_shows_orders_in_producao(self):
        pedido = create_order(
            tipo=Pedido.Tipo.PREFERENCIAL,
            itens=[{"prato_id": str(self.prato.id), "quantidade": 1}],
        )
        self.client.post(
            f"/api/v1/atendimento/lista/{pedido.id}/",
            {"acao": "PRODUCAO"},
            format="json",
        )

        response = self.client.get("/api/v1/fila/painel/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["pendentes"]), 1)
        self.assertEqual(response.json()["pendentes"][0]["tipo"], Pedido.Tipo.PREFERENCIAL)

    def test_finalizar_prato_api_finishes_item(self):
        pedido = create_order(
            tipo=Pedido.Tipo.NORMAL,
            itens=[{"prato_id": str(self.prato.id), "quantidade": 1}],
        )
        self.client.post(
            f"/api/v1/atendimento/lista/{pedido.id}/",
            {"acao": "PRODUCAO"},
            format="json",
        )
        fila = pedido.filas.get()

        response = self.client.post(f"/api/v1/fila/finalizar/{fila.id}/", {}, format="json")

        fila.refresh_from_db()
        pedido.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fila.status, FilaPrato.Status.FINALIZADO)
        self.assertEqual(pedido.status, Pedido.Status.FINALIZADO)

    def test_monitor_pedidos_groups_orders_by_status(self):
        pedido_pendente = create_order(
            tipo=Pedido.Tipo.NORMAL,
            itens=[{"prato_id": str(self.prato.id), "quantidade": 1}],
        )
        pedido_producao = create_order(
            tipo=Pedido.Tipo.NORMAL,
            itens=[{"prato_id": str(self.prato.id), "quantidade": 1}],
        )
        self.client.post(
            f"/api/v1/atendimento/lista/{pedido_producao.id}/",
            {"acao": "PRODUCAO"},
            format="json",
        )
        fila = pedido_producao.filas.get()
        self.client.post(f"/api/v1/fila/finalizar/{fila.id}/", {}, format="json")

        response = self.client.get("/api/v1/monitor/pedidos/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["pendentes"]), 1)
        self.assertEqual(body["pendentes"][0]["id"], str(pedido_pendente.id))
        self.assertEqual(body["pendentes"][0]["senha"], str(pedido_pendente.id).split("-")[0][:4].upper())
        self.assertEqual(len(body["prontos"]), 1)

    def test_pedidos_prontos_impressao_lists_only_unprinted_ready_orders(self):
        pedido = create_order(
            tipo=Pedido.Tipo.NORMAL,
            itens=[{"prato_id": str(self.prato.id), "quantidade": 1}],
        )
        self.client.post(
            f"/api/v1/atendimento/lista/{pedido.id}/",
            {"acao": "PRODUCAO"},
            format="json",
        )
        fila = pedido.filas.get()
        self.client.post(f"/api/v1/fila/finalizar/{fila.id}/", {}, format="json")

        response = self.client.get("/api/v1/monitor/pedidos-prontos-impressao/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["id"], str(pedido.id))
        self.assertEqual(body[0]["senha"], str(pedido.id).split("-")[0][:4].upper())

    def test_pedidos_prontos_impressao_claim_prevents_duplicate_fetch_before_ack(self):
        pedido = create_order(
            tipo=Pedido.Tipo.NORMAL,
            itens=[{"prato_id": str(self.prato.id), "quantidade": 1}],
        )
        self.client.post(
            f"/api/v1/atendimento/lista/{pedido.id}/",
            {"acao": "PRODUCAO"},
            format="json",
        )
        fila = pedido.filas.get()
        self.client.post(f"/api/v1/fila/finalizar/{fila.id}/", {}, format="json")

        first_response = self.client.get("/api/v1/monitor/pedidos-prontos-impressao/")
        second_response = self.client.get("/api/v1/monitor/pedidos-prontos-impressao/")
        pedido.refresh_from_db()

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(len(first_response.json()), 1)
        self.assertEqual(second_response.json(), [])
        self.assertIsNotNone(pedido.ready_print_claimed_at)

    def test_marcar_pedido_pronto_como_impresso_removes_it_from_print_queue(self):
        pedido = create_order(
            tipo=Pedido.Tipo.NORMAL,
            itens=[{"prato_id": str(self.prato.id), "quantidade": 1}],
        )
        self.client.post(
            f"/api/v1/atendimento/lista/{pedido.id}/",
            {"acao": "PRODUCAO"},
            format="json",
        )
        fila = pedido.filas.get()
        self.client.post(f"/api/v1/fila/finalizar/{fila.id}/", {}, format="json")

        response = self.client.post(
            f"/api/v1/monitor/pedidos/{pedido.id}/impresso/",
            {},
            format="json",
        )

        pedido.refresh_from_db()
        fila_response = self.client.get("/api/v1/monitor/pedidos-prontos-impressao/")

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(pedido.ready_printed_at)
        self.assertEqual(fila_response.json(), [])

    def test_print_queue_keeps_order_even_if_it_is_retirado_before_print_ack(self):
        pedido = create_order(
            tipo=Pedido.Tipo.NORMAL,
            itens=[{"prato_id": str(self.prato.id), "quantidade": 1}],
        )
        self.client.post(
            f"/api/v1/atendimento/lista/{pedido.id}/",
            {"acao": "PRODUCAO"},
            format="json",
        )
        fila = pedido.filas.get()
        self.client.post(f"/api/v1/fila/finalizar/{fila.id}/", {}, format="json")
        self.client.post(f"/api/v1/pedidos/retirar/{pedido.id}/", {}, format="json")

        response = self.client.get("/api/v1/monitor/pedidos-prontos-impressao/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["id"], str(pedido.id))

    def test_partial_finalization_keeps_order_in_producao_and_out_of_print_queue(self):
        pedido = create_order(
            tipo=Pedido.Tipo.NORMAL,
            itens=[{"prato_id": str(self.prato.id), "quantidade": 2}],
        )
        self.client.post(
            f"/api/v1/atendimento/lista/{pedido.id}/",
            {"acao": "PRODUCAO"},
            format="json",
        )
        fila = pedido.filas.order_by("created_at").first()

        response = self.client.post(f"/api/v1/fila/finalizar/{fila.id}/", {}, format="json")
        pedido.refresh_from_db()
        monitor_response = self.client.get("/api/v1/monitor/pedidos/")
        fila_impressao_response = self.client.get("/api/v1/monitor/pedidos-prontos-impressao/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(pedido.status, Pedido.Status.PRODUCAO)
        self.assertEqual(len(monitor_response.json()["preparando"]), 1)
        self.assertEqual(fila_impressao_response.json(), [])

    def test_finalizar_prato_api_returns_not_found_if_order_is_not_in_producao(self):
        pedido = create_order(
            tipo=Pedido.Tipo.NORMAL,
            itens=[{"prato_id": str(self.prato.id), "quantidade": 1}],
        )
        fila = pedido.filas.get()

        response = self.client.post(f"/api/v1/fila/finalizar/{fila.id}/", {}, format="json")

        self.assertEqual(response.status_code, 404)

    def test_finalizar_prato_api_is_idempotent_for_duplicate_submission(self):
        pedido = create_order(
            tipo=Pedido.Tipo.NORMAL,
            itens=[{"prato_id": str(self.prato.id), "quantidade": 1}],
        )
        self.client.post(
            f"/api/v1/atendimento/lista/{pedido.id}/",
            {"acao": "PRODUCAO"},
            format="json",
        )
        fila = pedido.filas.get()

        first_response = self.client.post(f"/api/v1/fila/finalizar/{fila.id}/", {}, format="json")
        second_response = self.client.post(f"/api/v1/fila/finalizar/{fila.id}/", {}, format="json")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 404)

    def test_multiple_ready_orders_are_listed_distinctly_in_print_queue(self):
        pedidos = []
        for _ in range(3):
            pedido = create_order(
                tipo=Pedido.Tipo.NORMAL,
                itens=[{"prato_id": str(self.prato.id), "quantidade": 1}],
            )
            self.client.post(
                f"/api/v1/atendimento/lista/{pedido.id}/",
                {"acao": "PRODUCAO"},
                format="json",
            )
            fila = pedido.filas.get()
            self.client.post(f"/api/v1/fila/finalizar/{fila.id}/", {}, format="json")
            pedidos.append(pedido)

        response = self.client.get("/api/v1/monitor/pedidos-prontos-impressao/")

        self.assertEqual(response.status_code, 200)
        ids_retornados = [item["id"] for item in response.json()]
        self.assertEqual(ids_retornados, [str(p.id) for p in pedidos])

    def test_retirar_pedido_api_requires_all_items_ready(self):
        pedido = create_order(
            tipo=Pedido.Tipo.NORMAL,
            itens=[{"prato_id": str(self.prato.id), "quantidade": 1}],
        )

        response = self.client.post(f"/api/v1/pedidos/retirar/{pedido.id}/", {}, format="json")

        self.assertEqual(response.status_code, 400)

    def test_producao_quantitativo_counts_pending_units(self):
        pedido = create_order(
            tipo=Pedido.Tipo.NORMAL,
            itens=[{"prato_id": str(self.prato.id), "quantidade": 2}],
        )
        self.client.post(
            f"/api/v1/atendimento/lista/{pedido.id}/",
            {"acao": "PRODUCAO"},
            format="json",
        )

        response = self.client.get("/api/v1/producao/quantitativo/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body[0]["prato__nome"], "Pastel")
        self.assertEqual(body[0]["total_produzir"], 2)


class LicensingMiddlewareTests(BaseApiTestCase):
    @override_settings(LICENSE_KEY="", LICENSE_EXPIRY=date(2026, 12, 31))
    def test_license_blocks_order_creation_routes(self):
        response = self.client.post(
            "/api/v1/pedidos/criar/",
            {"tipo": Pedido.Tipo.NORMAL, "itens": []},
            format="json",
        )

        self.assertEqual(response.status_code, 402)

    @override_settings(LICENSE_KEY="teste", LICENSE_EXPIRY=date(2020, 1, 1))
    def test_license_blocks_queue_routes_when_expired(self):
        response = self.client.get("/api/v1/fila/painel/")

        self.assertEqual(response.status_code, 402)

    @override_settings(LICENSE_KEY="teste", LICENSE_EXPIRY=date(2099, 1, 1))
    def test_valid_license_allows_request_to_reach_view(self):
        response = self.client.get("/api/v1/pratos/")

        self.assertEqual(response.status_code, 200)
