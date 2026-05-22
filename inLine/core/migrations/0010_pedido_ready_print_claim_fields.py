from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_filaprato_released_to_production_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="pedido",
            name="ready_print_claimed_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="pedido",
            name="ready_print_claim_token",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
    ]
