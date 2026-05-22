from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from core.models import FilaPrato, Pedido, Prato


class PageSmokeTests(TestCase):
    def setUp(self):
        prato = Prato.objects.create(nome="Pastel", preco=Decimal("10.00"), estoque=5)
        self.pedido = Pedido.objects.create(
            tipo=Pedido.Tipo.NORMAL,
            total=prato.preco,
        )

    def test_main_pages_render_successfully(self):
        paginas = [
            "/",
            "/caixa/",
            "/atendimento/",
            "/producao/",
            "/cadastrar-prato/",
            "/monitor/",
            "/atendimento/baixa-entrega/",
            "/producao/painel/",
            f"/acompanhamento/{self.pedido.id}/",
        ]

        for pagina in paginas:
            with self.subTest(pagina=pagina):
                response = self.client.get(pagina)
                self.assertEqual(response.status_code, 200)

    def test_dashboard_uses_local_date_after_21h_brasilia(self):
        pedido = Pedido.objects.create(
            tipo=Pedido.Tipo.NORMAL,
            total=self.pedido.total,
        )
        fila = FilaPrato.objects.create(
            pedido=pedido,
            prato=Prato.objects.get(nome="Pastel"),
            preco_unitario=Decimal("10.00"),
            status=FilaPrato.Status.FINALIZADO,
        )

        dia_operacional = timezone.datetime(2026, 5, 10, 20, 30, 0)
        dia_seguinte = timezone.datetime(2026, 5, 11, 9, 0, 0)
        created_at_local = timezone.make_aware(dia_operacional)
        finished_at_local = timezone.make_aware(dia_operacional)
        created_at_dia_seguinte = timezone.make_aware(dia_seguinte)

        FilaPrato.objects.filter(id=fila.id).update(
            created_at=created_at_local,
            finished_at=finished_at_local,
        )

        pedido_dia_seguinte = Pedido.objects.create(
            tipo=Pedido.Tipo.NORMAL,
            total=self.pedido.total,
        )
        fila_dia_seguinte = FilaPrato.objects.create(
            pedido=pedido_dia_seguinte,
            prato=Prato.objects.get(nome="Pastel"),
            preco_unitario=Decimal("10.00"),
            status=FilaPrato.Status.FINALIZADO,
        )
        FilaPrato.objects.filter(id=fila_dia_seguinte.id).update(
            created_at=created_at_dia_seguinte,
            finished_at=created_at_dia_seguinte,
        )

        agora_utc = timezone.datetime(2026, 5, 11, 0, 30, 0, tzinfo=dt_timezone.utc)
        with patch("core.views.timezone.now", return_value=agora_utc):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_geral"], 1)
        metricas = list(response.context["metricas_pratos"])
        self.assertEqual(metricas[0].vendidos_hoje, 1)
