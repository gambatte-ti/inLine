import uuid
from datetime import timedelta

from django.db import transaction, models
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Pedido, FilaPrato, TMA, Prato
from django.db.models import F

# =========================
# CAIXA
# =========================

@transaction.atomic
def create_order(tipo, itens):
    if not itens:
        raise ValueError("Pedido sem itens.")

    itens_normalizados = {}
    for item in itens:
        prato_id = str(item["prato_id"])
        quantidade = int(item["quantidade"])

        if quantidade <= 0:
            raise ValueError("Quantidade inválida no pedido.")

        itens_normalizados[prato_id] = itens_normalizados.get(prato_id, 0) + quantidade

    pratos = {
        str(prato.id): prato
        for prato in Prato.objects.filter(id__in=itens_normalizados.keys())
    }

    if len(pratos) != len(itens_normalizados):
        raise ValueError("Um ou mais pratos não foram encontrados.")

    total_acumulado = 0
    filas_para_criar = []

    for prato_id, qtd in itens_normalizados.items():
        prato = pratos[prato_id]

        atualizado = Prato.objects.filter(id=prato.id, estoque__gte=qtd).update(
            estoque=F("estoque") - qtd
        )
        if atualizado == 0:
            raise ValueError(f"Estoque insuficiente para {prato.nome}")

        total_acumulado += prato.preco * qtd
        filas_para_criar.extend(
            FilaPrato(
                prato=prato,
                preco_unitario=prato.preco,
            )
            for _ in range(qtd)
        )

    pedido = Pedido.objects.create(tipo=tipo, total=total_acumulado)

    for fila in filas_para_criar:
        fila.pedido = pedido

    FilaPrato.objects.bulk_create(filas_para_criar)
    return pedido

# =========================
# INICIAR PRATO
# =========================

def iniciar_producao_item(fila_id):
    item = FilaPrato.objects.get(id=fila_id)
    if not item.started_at:
        item.started_at = timezone.now()  # Registra o início REAL
        item.status = FilaPrato.Status.EM_PRODUCAO
        item.save(update_fields=['started_at', 'status'])
    return item


def release_order_to_production(pedido):
    agora = timezone.now()

    pedido.status = Pedido.Status.PRODUCAO
    pedido.save(update_fields=["status"])

    pedido.filas.exclude(status=FilaPrato.Status.CANCELADO).update(
        status=FilaPrato.Status.PENDENTE,
        released_to_production_at=agora,
    )

    return pedido


def recalculate_pedido_status(pedido):
    status_counts = {
        row["status"]: row["total"]
        for row in pedido.filas.values("status").annotate(total=models.Count("id"))
    }
    total_itens = sum(status_counts.values())

    if total_itens == 0:
        return pedido

    has_open_items = any(
        status_counts.get(status, 0) > 0
        for status in [FilaPrato.Status.PENDENTE, FilaPrato.Status.EM_PRODUCAO]
    )

    if has_open_items:
        if pedido.status in [Pedido.Status.PRODUCAO, Pedido.Status.FINALIZADO]:
            pedido.status = Pedido.Status.PRODUCAO
            pedido.save(update_fields=["status"])
        return pedido

    total_retirados = status_counts.get(FilaPrato.Status.RETIRADO, 0)
    total_cancelados = status_counts.get(FilaPrato.Status.CANCELADO, 0)

    if total_retirados == total_itens:
        if pedido.status != Pedido.Status.RETIRADO:
            pedido.status = Pedido.Status.RETIRADO
            pedido.save(update_fields=["status"])
        return pedido

    if total_cancelados == total_itens:
        if pedido.status != Pedido.Status.CANCELADO:
            pedido.status = Pedido.Status.CANCELADO
            pedido.save(update_fields=["status"])
        return pedido

    has_ready_items = any(
        status_counts.get(status, 0) > 0
        for status in [FilaPrato.Status.FINALIZADO, FilaPrato.Status.RETIRADO]
    )

    if has_ready_items:
        fields_to_update = []
        if pedido.status != Pedido.Status.FINALIZADO:
            pedido.status = Pedido.Status.FINALIZADO
            fields_to_update.append("status")
        if pedido.ready_printed_at is not None:
            pedido.ready_printed_at = None
            fields_to_update.append("ready_printed_at")
        if pedido.ready_print_claimed_at is not None:
            pedido.ready_print_claimed_at = None
            fields_to_update.append("ready_print_claimed_at")
        if pedido.ready_print_claim_token is not None:
            pedido.ready_print_claim_token = None
            fields_to_update.append("ready_print_claim_token")

        if fields_to_update:
            pedido.save(update_fields=fields_to_update)

    return pedido


def claim_ready_orders_for_print(limit=20, claim_timeout=timedelta(minutes=3)):
    now = timezone.now()
    stale_before = now - claim_timeout
    claim_token = uuid.uuid4()

    with transaction.atomic():
        candidate_ids = list(
            Pedido.objects.filter(
                status__in=[Pedido.Status.FINALIZADO, Pedido.Status.RETIRADO],
                ready_printed_at__isnull=True,
            )
            .filter(
                models.Q(ready_print_claimed_at__isnull=True)
                | models.Q(ready_print_claimed_at__lt=stale_before)
            )
            .order_by("created_at")
            .values_list("id", flat=True)[:limit]
        )

        if not candidate_ids:
            return []

        Pedido.objects.filter(
            id__in=candidate_ids,
            ready_printed_at__isnull=True,
        ).filter(
            models.Q(ready_print_claimed_at__isnull=True)
            | models.Q(ready_print_claimed_at__lt=stale_before)
        ).update(
            ready_print_claimed_at=now,
            ready_print_claim_token=claim_token,
        )

        return list(
            Pedido.objects.filter(ready_print_claim_token=claim_token)
            .prefetch_related("filas__prato")
            .order_by("created_at")
        )

# =========================
# FINALIZAÇÃO DE PRATO
# =========================



def finalize_prato(fila_id):
    try:
        with transaction.atomic():
            # 1. Busca o item com lock para evitar concorrência
            item = FilaPrato.objects.select_for_update().filter(id=fila_id).first()

            if not item or item.status in [
                FilaPrato.Status.FINALIZADO,
                FilaPrato.Status.RETIRADO,
                FilaPrato.Status.CANCELADO,
            ]:
                return None

            if item.pedido.status != Pedido.Status.PRODUCAO:
                return None

            agora = timezone.now()

            # 2. GRAVAÇÃO DOS TEMPOS (O CORAÇÃO DO TMA)
            # Se o item não tiver hora de início (pulou a etapa 'em produção'), 
            # assumimos que começou agora para não quebrar o cálculo.
            if not item.started_at:
                item.started_at = item.released_to_production_at or item.created_at

            item.finished_at = agora  # Define o fim da produção AGORA
            item.status = FilaPrato.Status.FINALIZADO
            
            # 3. SALVAMENTO EXPLÍCITO
            # Adicionamos os campos de tempo no update_fields
            item.save(update_fields=['status', 'finished_at', 'started_at', 'updated_at'])

            # 4. Atualização do Pedido (se todos os itens do pedido acabaram)
            pedido = item.pedido
            recalculate_pedido_status(pedido)
            
            return item
    except Exception as e:
        print(f"Erro no service finalize_prato: {e}")
        raise e


# =========================
# MÉTRICA TMA (janela fixa)
# =========================

def calculate_tma_per_prato():
    """
    Calcula o TMA focado na performance recente (Janela de até 10 unidades).
    Se houver < 10, calcula com o que houver. Se > 10, pega o lote mais recente.
    """
    # 1. Identifica pratos que possuem itens finalizados aguardando cálculo
    pratos_pendentes = FilaPrato.objects.filter(
        status=FilaPrato.Status.FINALIZADO, 
        usado_em_metrica=False,
        started_at__isnull=False,
        finished_at__isnull=False
    ).values('prato').annotate(total=models.Count('id'))

    for p in pratos_pendentes:
        prato_id = p['prato']
        try:
            with transaction.atomic():
                # 2. Busca o lote (até 10 itens) - selecionamos para update para evitar concorrência
                itens = list(
                    FilaPrato.objects.filter(
                        prato_id=prato_id,
                        status=FilaPrato.Status.FINALIZADO,
                        usado_em_metrica=False
                    )
                    .select_for_update()
                    .order_by('finished_at')[:10]
                )

                qtd = len(itens)
                if qtd == 0:
                    continue

                # 3. Cálculo da média do lote atual
                # Soma a diferença de tempo de cada item individualmente (preparo real)
                soma_segundos = sum([
                    max(0.0, (i.finished_at - i.started_at).total_seconds()) 
                    for i in itens
                ])
                
                media = soma_segundos / qtd

                # 4. Grava a nova métrica na tabela TMA
                TMA.objects.create(
                    prato_id=prato_id,
                    valor_tma_seg=media,
                    ultimo_prato_id=itens[-1].id # Referência para auditoria
                )

                # 5. Marca esses itens como processados
                FilaPrato.objects.filter(
                    id__in=[i.id for i in itens]
                ).update(usado_em_metrica=True)

        except Exception as e:
            print(f"Erro ao calcular TMA para prato {prato_id}: {e}")

# =========================
# RETIRADA DE PEDIDO (janela fixa)
# =========================

def registrar_retirada_total_pedido(pedido_id):
    try:
        with transaction.atomic():
            # 1. Busca o pedido e trava a linha no banco
            pedido = Pedido.objects.select_for_update().get(id=pedido_id)
            
            # 2. Conta quantos itens o pedido tem no total
            total_itens = pedido.filas.count()
            
            # 3. Conta quantos desses itens já estão FINALIZADOS
            total_finalizados = pedido.filas.filter(status=FilaPrato.Status.FINALIZADO).count()

            # REGRA DE OURO: Só passa se o total for igual ao finalizado
            if total_itens != total_finalizados:
                raise ValidationError(
                    f"Impossível retirar: O pedido tem {total_itens} itens, mas apenas {total_finalizados} estão prontos."
                )

            # 4. Se chegou aqui, todos estão prontos. Então damos baixa em tudo:
            pedido.filas.all().update(
                status=FilaPrato.Status.RETIRADO, 
                delivered_at=timezone.now()
            )
            
            # 5. Atualiza o status do Pedido pai
            recalculate_pedido_status(pedido)
            
            return pedido
            
    except Pedido.DoesNotExist:
        return None


def mark_ready_order_as_printed(pedido_id):
    with transaction.atomic():
        pedido = Pedido.objects.select_for_update().filter(id=pedido_id).first()

        if not pedido:
            return None

        if pedido.status not in [Pedido.Status.FINALIZADO, Pedido.Status.RETIRADO]:
            return pedido

        update_fields = []
        if pedido.ready_printed_at is None:
            pedido.ready_printed_at = timezone.now()
            update_fields.append("ready_printed_at")
        if pedido.ready_print_claimed_at is not None:
            pedido.ready_print_claimed_at = None
            update_fields.append("ready_print_claimed_at")
        if pedido.ready_print_claim_token is not None:
            pedido.ready_print_claim_token = None
            update_fields.append("ready_print_claim_token")

        if update_fields:
            pedido.save(update_fields=update_fields)

        return pedido
