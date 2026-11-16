"""Regenerate docs/backend/eraser/*.eraser from the Django models.

Run from backend/: DEBUG=1 .venv/bin/python manage.py shell < ../docs/backend/eraser/generate.py
"""
from pathlib import Path
from django.apps import apps
from django.db import models

OUT = Path("../docs/backend/eraser")
APPS = [("accounts", "user", "blue"), ("venues", "map-pin", "green"), ("teams", "users", "orange"),
        ("bookings", "calendar", "purple"), ("billing", "dollar-sign", "red"), ("wellness", "heart", "yellow"),
        ("chat", "message-circle", "pink")]
SIMPLE = {models.CharField: "varchar", models.EmailField: "varchar", models.FileField: "varchar", models.URLField: "varchar",
          models.TextField: "text", models.BooleanField: "boolean", models.DateTimeField: "timestamp",
          models.DateField: "date", models.TimeField: "time", models.PositiveSmallIntegerField: "smallint",
          models.SmallIntegerField: "smallint", models.PositiveIntegerField: "int", models.IntegerField: "int"}

def kind(f):
    if isinstance(f, (models.AutoField, models.BigAutoField)):
        return "bigint pk"
    if isinstance(f, models.ForeignKey):
        t = "bigint"
    elif isinstance(f, models.DecimalField):
        t = f"decimal({f.max_digits},{f.decimal_places})"
    else:
        t = next(v for k, v in SIMPLE.items() if type(f) is k)
    return t + (" unique" if f.unique else "") + (" null" if f.null else "")

SKIP = {"password", "last_login", "is_superuser"}  # Django auth internals, left out as before

def tables(label):
    """The app's models in definition order, each many-to-many table right after the model that declares it."""
    found = []
    for m in apps.get_app_config(label).get_models():
        found.append(m)
        found += [f.remote_field.through for f in m._meta.local_many_to_many
                  if f.remote_field.through._meta.auto_created and f.remote_field.through._meta.db_table != "users_groups"
                  and f.remote_field.through._meta.db_table != "users_user_permissions"]
    return found

def emit(label, icon, color, ms):
    body, links = [], []
    for m in ms:
        t = m._meta.db_table
        body.append(f"{t} [icon: {icon}, color: {color}] {{")
        for f in m._meta.local_fields:
            if f.name in SKIP:
                continue
            body.append(f"  {f.column} {kind(f)}")
            if isinstance(f, models.ForeignKey):
                links.append(f"{t}.{f.column} > {f.related_model._meta.db_table}.{f.related_model._meta.pk.column}")
        body.append("}\n")
    return body, links

overview_body, overview_links = [], []
for label, icon, color in APPS:
    body, links = emit(label, icon, color, tables(label))
    overview_body += body; overview_links += links
    (OUT / f"{label}.eraser").write_text(f"// PASS schema - {label}\n\n" + "\n".join(body) + "\n" + "\n".join(links) + "\n")
(OUT / "overview.eraser").write_text(
    "// PASS schema - all apps. Colour by Django app: accounts = blue, venues = green, teams = orange, bookings = purple, "
    "billing = red, wellness = yellow, chat = pink\n\n" + "\n".join(overview_body) + "\n" + "\n".join(overview_links) + "\n")
print("tables:", sum(len(tables(a)) for a, _, _ in APPS))
