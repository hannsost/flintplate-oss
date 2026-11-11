# Fictional demo data only: QuickWork, people, emails and companies are invented.
"""Demo-Seed: QuickWork Personalservice GmbH

Simuliert den realistischen Workflow einer Zeitarbeitsfirma:

  Phase 1 – Tenant + HR-Team anlegen
    • 1 Tenant "QuickWork Personalservice GmbH"
    • 3 HR-User: 1 Admin (Thomas Bergmann), 2 Recruiter (Max Müller, Lisa Brandt)

  Phase 2 – Kandidaten bewerben sich mit vollständigen Profilen
    • 8 Kandidaten registrieren sich (role=candidate)
    • Jeder Kandidat hat vollständiges Profil: Berufserfahrung, Ausbildung, Skills

  Phase 2.5 – Hiring-Prozess (realistischer Bewerbungsfluss)
    • Kandidaten bewerben sich bei QuickWork als Zeitarbeiter
    • Application: applied → screening → interview
    • InterviewSchedule: terminiert, durchgeführt, bestätigt
    • InterviewScorecard: Bewertung durch Recruiter
    • Status: interview → offer (= eingestellt)

  Phase 3 – Kandidaten werden als Zeitarbeiter eingestellt
    • Triggered durch: POST /zeitarbeit/workers/hire-from-application
    • Setzt role=worker, legt WorkerSettings an, Application status → offer

  Phase 4 – Operativdaten (Einsätze, Zeiten, Dokumente etc.)
    • Kundenfirmen (LogiPort, NordBeck, CityGlanz)
    • Einsatzplan Okt 2025 – Mär 2026
    • Zeiteinträge (Okt–Feb genehmigt, Mär offen)
    • Abwesenheiten, Gehaltszettel, Equipment, Tasks, Nachrichten
    • Echte PDFs via WeasyPrint (Arbeitsvertrag, Gabelstaplerschein, etc.)

Usage (im Backend-Container):
  python scripts/seed_demo_quickwork.py
  python scripts/seed_demo_quickwork.py --reset  # löscht QuickWork-Daten und erstellt neu
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.absences.models import Absence  # noqa: F401
from app.admin.models import Customer, CustomerModule  # noqa: F401
from app.applications.models import Application, ApplicationHistory, ApplicationStatus  # noqa: F401

# Import ALL models upfront so SQLAlchemy mapper can resolve FK relationships
# before any flush happens (prevents NoReferencedTableError for cross-module FKs)
from app.companies.models import Company  # noqa: F401
from app.dms.models import DocCategory, Document  # noqa: F401
from app.equipment.models import EquipmentAssignment, EquipmentItem  # noqa: F401
from app.interviews.models import InterviewSchedule, InterviewScorecard  # noqa: F401
from app.jobs.models import JobPosting  # noqa: F401
from app.messages.models import Message, MessageThread  # noqa: F401
from app.payroll.models import PayStub  # noqa: F401
from app.profiles.models import CandidateProfile, Education, Skill, WorkExperience  # noqa: F401
from app.security import hash_password  # noqa: F401
from app.tasks.models import Task  # noqa: F401
from app.teams.models import Team  # noqa: F401
from app.users.models import PrivacyConsent, User  # noqa: F401
from app.worker.assignment_models import WorkerAssignment  # noqa: F401
from app.worker.models import ALL_MODULES, WorkerSettings  # noqa: F401
from app.worker.time_models import TimeEntry  # noqa: F401
from app.zeitarbeit.models import Disposition, TempWorkerAvailability, WorkAssignment  # noqa: F401

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://hireos:hireos@db:5432/hireos",
)

STATIC_DIR = Path("/app/static/demo")
STATIC_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# PDF generation helpers
# ─────────────────────────────────────────────────────────────────────────────


def _css() -> str:
    return """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: Arial, sans-serif; font-size: 11pt; color: #1a1a1a;
           padding: 2cm 2.5cm; line-height: 1.5; }
    h1 { font-size: 18pt; color: #059669; margin-bottom: 4pt; }
    h2 { font-size: 13pt; color: #374151; margin: 16pt 0 6pt;
         border-bottom: 1px solid #d1fae5; padding-bottom: 3pt; }
    p  { margin-bottom: 6pt; }
    .header { display: flex; justify-content: space-between;
              align-items: flex-start; margin-bottom: 24pt; }
    .logo   { font-size: 20pt; font-weight: 700; color: #059669; }
    .logo span { color: #111; }
    .meta   { text-align: right; font-size: 9pt; color: #6b7280; }
    .badge  { display: inline-block; background: #d1fae5; color: #065f46;
              padding: 2pt 8pt; border-radius: 4pt; font-size: 9pt;
              font-weight: 600; margin-bottom: 12pt; }
    table   { width: 100%; border-collapse: collapse; margin: 8pt 0; }
    th      { background: #f0fdf4; text-align: left; padding: 5pt 8pt;
              font-size: 9.5pt; font-weight: 600; border: 1px solid #d1fae5; }
    td      { padding: 5pt 8pt; font-size: 9.5pt; border: 1px solid #e5e7eb; }
    tr:nth-child(even) td { background: #f9fafb; }
    .sign   { margin-top: 40pt; display: flex; justify-content: space-between; }
    .sign-box { text-align: center; }
    .sign-line { border-top: 1px solid #374151; width: 160pt; margin: 0 auto 4pt;
                 padding-top: 4pt; }
    .footer { position: fixed; bottom: 1cm; left: 2.5cm; right: 2.5cm;
              text-align: center; font-size: 8pt; color: #9ca3af;
              border-top: 1px solid #e5e7eb; padding-top: 4pt; }
    .highlight { background: #fef3c7; padding: 8pt 12pt;
                 border-left: 3pt solid #f59e0b; margin: 8pt 0; }
    ul { margin-left: 16pt; margin-bottom: 8pt; }
    """


def _header_html(title: str, doc_nr: str, date_str: str) -> str:
    return f"""
    <div class="header">
      <div>
        <div class="logo">Quick<span>Work</span></div>
        <div style="font-size:9pt;color:#6b7280">
          QuickWork Personalservice GmbH<br>Hafenstraße 42 · 20457 Hamburg
        </div>
      </div>
      <div class="meta"><strong>{title}</strong><br>Nr.: {doc_nr}<br>Datum: {date_str}</div>
    </div>
    """


def _footer_html() -> str:
    return """
    <div class="footer">
      QuickWork Personalservice GmbH · HRB 123456 HH · USt-IdNr. DE123456789 ·
      GF: Thomas Bergmann · IBAN: DE89 2005 0550 1234 5678 00
    </div>
    """


def _render_pdf(html: str) -> bytes:
    try:
        from weasyprint import HTML

        return HTML(string=html).write_pdf()
    except Exception:
        return html.encode("utf-8")


def gen_arbeitsvertrag(
    worker_name: str, start: str, rate: str, role: str, customer: str, doc_id: str
) -> bytes:
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
    <style>{_css()}</style></head><body>
    {_header_html("ARBEITSVERTRAG", f"AV-{doc_id[:8].upper()}", start)}
    <div class="badge">Zeitarbeit · befristet</div>
    <h1>Arbeitsvertrag</h1>
    <p>zwischen der <strong>QuickWork Personalservice GmbH</strong>, Hafenstraße 42, 20457 Hamburg
    – nachfolgend <em>Arbeitgeber</em> –</p>
    <p>und <strong>{worker_name}</strong> – nachfolgend <em>Arbeitnehmer</em> –</p>
    <h2>§ 1 Tätigkeit und Einsatz</h2>
    <table>
      <tr><th>Position</th><td>{role}</td></tr>
      <tr><th>Kundenunternehmen</th><td>{customer}</td></tr>
      <tr><th>Beginn</th><td>{start}</td></tr>
      <tr><th>Befristung</th><td>18 Monate, längstens bis 31.03.2027</td></tr>
    </table>
    <h2>§ 2 Vergütung</h2>
    <table>
      <tr><th>Stundenlohn (brutto)</th><td>{rate} €</td></tr>
      <tr><th>Zuschläge Nacht (20–6 Uhr)</th><td>25 %</td></tr>
      <tr><th>Zuschläge Sonntag</th><td>50 %</td></tr>
      <tr><th>Urlaubsanspruch</th><td>24 Werktage / Jahr</td></tr>
      <tr><th>Auszahlungstermin</th><td>letzter Werktag des Monats</td></tr>
    </table>
    <h2>§ 3 Arbeitszeit</h2>
    <p>Die regelmäßige Arbeitszeit beträgt 40 Stunden wöchentlich. Überstunden werden im
    Verhältnis 1:1 abgegolten.</p>
    <h2>§ 4 Schlussbestimmungen</h2>
    <p>Änderungen bedürfen der Schriftform. Gerichtsstand ist Hamburg.</p>
    <div class="sign">
      <div class="sign-box">
        <div class="sign-line"></div>
        <p>QuickWork Personalservice GmbH</p>
      </div>
      <div class="sign-box">
        <div class="sign-line"></div>
        <p>{worker_name}</p>
      </div>
    </div>
    {_footer_html()}</body></html>"""
    return _render_pdf(html)


def gen_gabelstapler(worker_name: str, issue: str, expiry: str, doc_id: str) -> bytes:
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
    <style>{_css()}</style></head><body>
    {_header_html("BEFÄHIGUNGSNACHWEIS", f"GS-{doc_id[:8].upper()}", issue)}
    <h1>Befähigungsnachweis Gabelstapler</h1>
    <div class="badge">BGG 925 / DGUV 308-001</div>
    <p>Hiermit wird bestätigt, dass <strong>{worker_name}</strong>
    eine Ausbildung zum sicheren Führen von Flurförderzeugen erfolgreich abgeschlossen hat.</p>
    <h2>Ausbildungsnachweis</h2>
    <table>
      <tr><th>Theorie</th><td>8 Stunden</td></tr>
      <tr><th>Praxis</th><td>16 Stunden</td></tr>
      <tr><th>Prüfung</th><td>bestanden</td></tr>
      <tr><th>Fahrzeugklassen</th><td>Gegengewichtsstapler bis 5 t, Schubmaststapler</td></tr>
      <tr><th>Ausgestellt am</th><td>{issue}</td></tr>
      <tr><th>Gültig bis</th><td><strong>{expiry}</strong></td></tr>
      <tr><th>Ausbildungseinrichtung</th><td>DEKRA Industrial GmbH, Hamburg</td></tr>
    </table>
    <div class="highlight">
      Dieser Nachweis berechtigt zur Führung von Gabelstaplern nur in Verbindung mit
      betrieblicher Einweisung gemäß § 9 DGUV-V 68.
    </div>
    <div class="sign">
      <div class="sign-box">
        <div class="sign-line"></div>
        <p>Prüfer · DEKRA Industrial GmbH</p>
      </div>
      <div class="sign-box">
        <div class="sign-line"></div>
        <p>{worker_name}</p>
      </div>
    </div>
    {_footer_html()}</body></html>"""
    return _render_pdf(html)


def gen_unterweisung(worker_name: str, date_str: str, customer: str, doc_id: str) -> bytes:
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
    <style>{_css()}</style></head><body>
    {_header_html("SICHERHEITSUNTERWEISUNG", f"SU-{doc_id[:8].upper()}", date_str)}
    <h1>Sicherheitsunterweisung</h1>
    <div class="badge">§ 12 ArbSchG · DGUV Vorschrift 1</div>
    <p>Einsatzort: <strong>{customer}</strong> · Unterwiesen: <strong>{worker_name}</strong></p>
    <h2>1. Allgemeine Sicherheitsregeln</h2>
    <ul>
      <li>PSA (Schutzschuhe S3, Warnweste, Schutzhelm) ist Pflicht</li>
      <li>Fluchtwege und Notausgänge sind stets freizuhalten</li>
      <li>Rauchen nur in ausgewiesenen Bereichen</li>
    </ul>
    <h2>2. Verhalten im Notfall</h2>
    <table>
      <tr><th>Notruf intern</th><td>111</td></tr>
      <tr><th>Feuerwehr / Rettung</th><td>112</td></tr>
      <tr><th>Versammlungspunkt</th><td>Parkplatz Ost, Tor 3</td></tr>
    </table>
    <h2>3. Bestätigung</h2>
    <p>Ich bestätige die Kenntnisnahme der Sicherheitsanweisungen.</p>
    <div class="sign">
      <div class="sign-box">
        <div class="sign-line"></div>
        <p>Unterweisender · {customer}</p>
      </div>
      <div class="sign-box">
        <div class="sign-line"></div>
        <p>{worker_name}</p>
      </div>
    </div>
    {_footer_html()}</body></html>"""
    return _render_pdf(html)


def gen_personalfragebogen(
    worker_name: str, dob: str, address: str, iban: str, doc_id: str
) -> bytes:
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
    <style>{_css()}</style></head><body>
    {_header_html("PERSONALFRAGEBOGEN", f"PF-{doc_id[:8].upper()}",
                  date.today().strftime("%d.%m.%Y"))}
    <h1>Personalfragebogen</h1>
    <div class="badge">Vertraulich · Nur intern</div>
    <h2>Persönliche Daten</h2>
    <table>
      <tr><th>Name</th><td>{worker_name}</td></tr>
      <tr><th>Geburtsdatum</th><td>{dob}</td></tr>
      <tr><th>Anschrift</th><td>{address}</td></tr>
      <tr><th>Staatsangehörigkeit</th><td>Deutsch</td></tr>
    </table>
    <h2>Bankverbindung</h2>
    <table>
      <tr><th>IBAN</th><td>{iban}</td></tr>
      <tr><th>Kreditinstitut</th><td>Hamburger Sparkasse (Haspa)</td></tr>
    </table>
    <h2>Steuerklasse</h2>
    <table>
      <tr><th>Steuerklasse</th><td>I</td></tr>
      <tr><th>Konfession</th><td>keine</td></tr>
    </table>
    <div class="sign">
      <div class="sign-box">
        <div class="sign-line"></div>
        <p>{worker_name} · Datum, Unterschrift</p>
      </div>
    </div>
    {_footer_html()}</body></html>"""
    return _render_pdf(html)


def gen_lohnzettel(
    worker_name: str, month: str, gross: int, net: int, hours: int, doc_id: str
) -> bytes:
    tax = int(gross * 0.19)
    sv = gross - net - tax
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
    <style>{_css()}</style></head><body>
    {_header_html("GEHALTSABRECHNUNG", f"LA-{doc_id[:8].upper()}",
                  date.today().strftime("%d.%m.%Y"))}
    <h1>Gehaltsabrechnung {month}</h1>
    <p>Arbeitnehmer: <strong>{worker_name}</strong></p>
    <h2>Abrechnungsübersicht</h2>
    <table>
      <tr><th>Stunden</th><td>{hours} h</td></tr>
      <tr><th>Bruttogehalt</th><td>{gross/100:.2f} €</td></tr>
    </table>
    <table style="margin-top:8pt">
      <tr><th>Lohnsteuer (ca. 19 %)</th><td>- {tax/100:.2f} €</td></tr>
      <tr><th>Sozialversicherung (AN)</th><td>- {sv/100:.2f} €</td></tr>
    </table>
    <table style="margin-top:8pt">
      <tr><th style="background:#d1fae5">Nettoauszahlung</th>
          <th style="background:#d1fae5;text-align:right">{net/100:.2f} €</th></tr>
    </table>
    {_footer_html()}</body></html>"""
    return _render_pdf(html)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _save_pdf(filename: str, data: bytes) -> tuple[str, int]:
    p = STATIC_DIR / filename
    p.write_bytes(data)
    return f"/static/demo/{filename}", len(data)


def _checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _workdays(y: int, m: int) -> list[date]:
    first = date(y, m, 1)
    last = (date(y, m + 1, 1) if m < 12 else date(y + 1, 1, 1)) - timedelta(days=1)
    d, result = first, []
    while d <= last:
        if d.weekday() < 5:
            result.append(d)
        d += timedelta(days=1)
    return result


def _dt(d: date, h: int, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


async def seed(reset: bool = False) -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        if reset:
            await _reset(db)

        # ── Phase 1: Tenant + HR-Team ─────────────────────────────────────
        print("\n━━━ Phase 1: Tenant + HR-Team ━━━")
        tenant_id = await _seed_tenant(db)
        hr = await _seed_hr_users(db, tenant_id)

        # ── Phase 2: Kandidaten anlegen ───────────────────────────────────
        print("\n━━━ Phase 2: Kandidaten (mit Profilen) ━━━")
        candidates = await _seed_candidates(db)

        # ── Phase 2.5: Hiring-Prozess ─────────────────────────────────────
        print("\n━━━ Phase 2.5: Hiring-Prozess (Bewerbung → Interview → Offer) ━━━")
        applications = await _seed_hiring_process(db, tenant_id, hr, candidates)

        # ── Phase 3: Einstellung als Zeitarbeiter ─────────────────────────
        print("\n━━━ Phase 3: Einstellung als Zeitarbeiter ━━━")
        workers = await _hire_as_workers(db, tenant_id, hr, candidates, applications)

        # ── Phase 4: Operativdaten ────────────────────────────────────────
        print("\n━━━ Phase 4: Operativdaten ━━━")
        customers_map = await _seed_customers(db, tenant_id)
        await _seed_einsaetze(db, tenant_id, workers, customers_map, hr)
        assignments = await _seed_assignments(db, tenant_id, workers, customers_map, hr)
        await _seed_time_entries(db, tenant_id, workers, assignments, hr)
        await _seed_absences(db, tenant_id, workers, hr)
        await _seed_paystubs(db, tenant_id, workers, hr)
        await _seed_equipment(db, tenant_id, workers, hr)
        await _seed_tasks(db, tenant_id, workers, hr)
        await _seed_messages(db, tenant_id, workers, hr)
        await _seed_documents(db, tenant_id, workers, hr)

        await db.commit()

    await engine.dispose()

    print("\n" + "═" * 60)
    print("✅ QuickWork Demo-Seed abgeschlossen!")
    print("═" * 60)
    print("  Tenant:   QuickWork Personalservice GmbH")
    print()
    print("  HR-Logins:")
    print("    Admin:     thomas.bergmann@quickwork.de  /  QuickWork2025!")
    print("    Recruiter: max.mueller@quickwork.de      /  QuickWork2025!")
    print("    Recruiter: lisa.brandt@quickwork.de      /  QuickWork2025!")
    print()
    print("  Worker-Logins (alle Passwort: Worker2025!):")
    print("    kalle.brenner@quickwork.de")
    print("    mehmet.demir@quickwork.de")
    print("    sabrina.sonntag@quickwork.de")
    print("    bruno.bergmann@quickwork.de")
    print("    greta.fleissig@quickwork.de")
    print("    lukas.frisch@quickwork.de")
    print("    klara.stern@quickwork.de")
    print("    inge.hoffmann@quickwork.de")
    print("═" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 – Tenant + HR
# ─────────────────────────────────────────────────────────────────────────────


async def _reset(db: AsyncSession) -> None:

    print("🗑  Reset: Lösche bestehende QuickWork-Daten …")
    row = await db.execute(select(Customer).where(Customer.slug == "quickwork"))
    tenant = row.scalar_one_or_none()
    if not tenant:
        print("   Kein Tenant gefunden.")
        return
    await db.delete(tenant)
    await db.commit()
    print("   ✓ Gelöscht.")


async def _seed_tenant(db: AsyncSession) -> uuid.UUID:

    row = await db.execute(select(Customer).where(Customer.slug == "quickwork"))
    existing = row.scalar_one_or_none()
    if existing:
        print("   ℹ  Tenant vorhanden – überspringe.")
        return existing.id

    t = Customer(
        name="QuickWork Personalservice GmbH",
        slug="quickwork",
        type="zeitarbeit",
        plan="professional",
        status="active",
        contact_email="info@quickwork.de",
        contact_name="Thomas Bergmann",
        phone="+49 40 8765 4321",
        address="Hafenstraße 42",
        city="Hamburg",
        country="DE",
        primary_color="#059669",
        contract_start=datetime(2024, 1, 1),
    )
    db.add(t)
    await db.flush()

    for module_key in [
        "zeitarbeit_pool",
        "dms",
        "kanban_pipeline",
        "analytics_advanced",
        "ai_cv_parser",
        "org_charts",
        "interview_scheduling",
    ]:
        db.add(CustomerModule(customer_id=t.id, module_key=module_key, enabled=True))

    await db.flush()
    print(f"   ✓ Tenant erstellt: QuickWork Personalservice GmbH (ID {t.id})")
    return t.id


async def _seed_hr_users(db: AsyncSession, tenant_id: uuid.UUID) -> dict:

    hr_data = [
        ("thomas.bergmann@quickwork.de", "Thomas Bergmann", "admin", "admin"),
        ("max.mueller@quickwork.de", "Max Müller", "recruiter", "max"),
        ("lisa.brandt@quickwork.de", "Lisa Brandt", "recruiter", "lisa"),
        ("jana.fischer@quickwork.de", "Jana Fischer", "recruiter", "jana"),
    ]

    result: dict = {}
    for email, name, role, key in hr_data:
        row = await db.execute(select(User).where(User.email == email))
        u = row.scalar_one_or_none()
        if not u:
            u = User(
                email=email,
                full_name=name,
                hashed_password=hash_password("QuickWork2025!"),
                role=role,
                tenant_id=tenant_id,
                is_active=True,
                is_verified=True,
            )
            db.add(u)
            await db.flush()
            db.add(
                PrivacyConsent(
                    user_id=u.id,
                    terms_accepted=True,
                    terms_accepted_at=datetime(2024, 1, 5),
                    ai_opt_in=True,
                    ai_opt_in_at=datetime(2024, 1, 5),
                )
            )
            await db.flush()
        else:
            # Ensure tenant_id is set even for pre-existing users
            if u.tenant_id is None:
                u.tenant_id = tenant_id
                await db.flush()
        result[key] = u
        print(f"   ✓ HR: {name} ({role})")

    # Create a Company record for QuickWork and link all HR users
    from app.companies.models import Company

    row = await db.execute(select(Company).where(Company.name == "QuickWork Personalservice GmbH"))
    company = row.scalar_one_or_none()
    if not company:
        admin_user = result.get("admin")
        company = Company(
            name="QuickWork Personalservice GmbH",
            website="https://quickwork.de",
            description="Zeitarbeit und Personalvermittlung in Hamburg und Umgebung.",
            location="Hamburg",
            created_by=admin_user.id if admin_user else None,
        )
        db.add(company)
        await db.flush()
        print(f"   ✓ Company erstellt: QuickWork Personalservice GmbH (ID {company.id})")

    for u in result.values():
        if u.company_id is None:
            u.company_id = company.id
    await db.flush()

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 – Kandidaten mit vollständigen Profilen
# ─────────────────────────────────────────────────────────────────────────────


async def _seed_candidates(db: AsyncSession) -> list:
    """Erstellt Kandidaten (role=candidate) mit vollständigen Profilen.

    Dies simuliert: Kandidaten registrieren sich auf der Plattform oder
    werden von einem Recruiter importiert.
    """
    from app.security import hash_password

    candidates_data = [
        {
            "email": "kalle.brenner@quickwork.de",
            "full_name": "Kalle Brenner",
            "key": "Kalle",
            "profile": {
                "headline": "Gabelstapler-Fahrer & Lagermitarbeiter",
                "summary": (
                    "Erfahrener Lagerlogistiker mit über 8 Jahren Berufserfahrung in der "
                    "Hafenlogistik. Gabelstaplerschein BGG 925 vorhanden, geübt im Umgang "
                    "mit Schwergut und zeitkritischen Schichten."
                ),
                "location": "Hamburg-Veddel",
                "phone": "+49 175 1234001",
            },
            "experiences": [
                {
                    "company": "Hamburger Hafen und Logistik AG (HHLA)",
                    "title": "Gabelstapler-Fahrer",
                    "start_date": date(2017, 3, 1),
                    "end_date": date(2025, 8, 31),
                    "is_current": False,
                    "description": "Wareneingang, -ausgabe und innerbetrieblicher Transport. Tägliche Bedienung von Gegengewichts- und Schubmaststaplern bis 5t.",
                },
                {
                    "company": "SpedEx Lagerlogistik GmbH",
                    "title": "Lagerhelfer",
                    "start_date": date(2014, 6, 1),
                    "end_date": date(2017, 2, 28),
                    "is_current": False,
                    "description": "Kommissionierung, Verpackung und Bestandspflege.",
                },
            ],
            "educations": [
                {
                    "institution": "Berufsschule Hamburg-Mitte",
                    "degree": "Ausbildung",
                    "field_of_study": "Fachkraft für Lagerlogistik",
                    "start_date": date(2011, 9, 1),
                    "end_date": date(2014, 6, 30),
                },
            ],
            "skills": [
                ("Gabelstapler BGG 925", "Zertifizierung", "expert", 8),
                ("Lagerlogistik", "Fachkompetenz", "expert", 10),
                ("SAP WM", "Software", "intermediate", 5),
                ("Schichtarbeit", "Arbeitsmethodik", "advanced", 8),
                ("Englisch", "Sprache", "beginner", 1),
            ],
            "completeness": 88,
        },
        {
            "email": "mehmet.demir@quickwork.de",
            "full_name": "Mehmet Demir",
            "key": "Mehmet",
            "profile": {
                "headline": "Lagermitarbeiter – Flexibel, zuverlässig, erfahren",
                "summary": (
                    "Zuverlässiger Lager- und Produktionsmitarbeiter mit 5 Jahren Erfahrung "
                    "in verschiedenen Schichtmodellen. Schnell einarbeitungsfähig."
                ),
                "location": "Hamburg-Rothenburgsort",
                "phone": "+49 175 1234002",
            },
            "experiences": [
                {
                    "company": "Amazon Fulfillment Center Hamburg",
                    "title": "Lagermitarbeiter Nachtschicht",
                    "start_date": date(2020, 4, 1),
                    "end_date": date(2025, 7, 31),
                    "is_current": False,
                    "description": "Wareneingang, Pick & Pack, Qualitätsprüfung in der Nachtschicht.",
                },
                {
                    "company": "Rewe Logistik GmbH",
                    "title": "Kommissionierer",
                    "start_date": date(2017, 1, 1),
                    "end_date": date(2020, 3, 31),
                    "is_current": False,
                    "description": "Lebensmittellogistik, Kühlbereich, RF-Scanner.",
                },
            ],
            "educations": [
                {
                    "institution": "BBS Logistik Hamburg",
                    "degree": "Berufsausbildung",
                    "field_of_study": "Fachlagerist",
                    "start_date": date(2014, 9, 1),
                    "end_date": date(2016, 8, 31),
                },
            ],
            "skills": [
                ("Kommissionierung", "Fachkompetenz", "expert", 7),
                ("RF-Scanner", "Werkzeug", "advanced", 5),
                ("Nachtschicht", "Arbeitsmethodik", "advanced", 5),
                ("Türkisch", "Sprache", "expert", 0),
                ("Deutsch", "Sprache", "advanced", 0),
            ],
            "completeness": 82,
        },
        {
            "email": "sabrina.sonntag@quickwork.de",
            "full_name": "Sabrina Sonntag",
            "key": "Sabrina",
            "profile": {
                "headline": "Reinigungsfachkraft – Büro & Gebäudereinigung",
                "summary": (
                    "Gewissenhafte Reinigungsfachkraft mit Erfahrung in Büro- und "
                    "Industriereinigung. Suche Teilzeitstelle mit geregelten Arbeitszeiten."
                ),
                "location": "Hamburg-Hammerbrook",
                "phone": "+49 175 1234003",
            },
            "experiences": [
                {
                    "company": "Piepenbrock Unterhaltsreinigung",
                    "title": "Reinigungsfachkraft",
                    "start_date": date(2018, 2, 1),
                    "end_date": date(2025, 6, 30),
                    "is_current": False,
                    "description": "Unterhaltsreinigung in Büros, Treppenhäusern und öffentlichen Gebäuden. Spezialreinigung nach DGUV.",
                },
            ],
            "educations": [],
            "skills": [
                ("Gebäudereinigung", "Fachkompetenz", "expert", 7),
                ("Hygieneschulung", "Zertifizierung", "advanced", 3),
                ("Maschinenreinigung", "Werkzeug", "intermediate", 4),
                ("Deutsch", "Sprache", "expert", 0),
            ],
            "completeness": 72,
        },
        {
            "email": "bruno.bergmann@quickwork.de",
            "full_name": "Bruno Bergmann",
            "key": "Bruno",
            "profile": {
                "headline": "CNC-Maschinenführer & Produktionstechniker",
                "summary": (
                    "Erfahrener Maschinenführer mit Schwerpunkt CNC-Fräsen und -Drehen. "
                    "Langjährige Erfahrung in der metallverarbeitenden Industrie. "
                    "Teamleiter-Erfahrung in der Früh- und Spätschicht."
                ),
                "location": "Hamburg-Veddel",
                "phone": "+49 175 1234004",
            },
            "experiences": [
                {
                    "company": "Blohm+Voss Repair GmbH",
                    "title": "CNC-Maschinenführer",
                    "start_date": date(2010, 6, 1),
                    "end_date": date(2025, 5, 31),
                    "is_current": False,
                    "description": "Bedienung und Rüsten von CNC-Fräs- und Drehmaschinen, Qualitätskontrolle nach DIN EN ISO 9001.",
                },
                {
                    "company": "Metzner Metallbau",
                    "title": "Metallhelfer",
                    "start_date": date(2005, 3, 1),
                    "end_date": date(2010, 5, 31),
                    "is_current": False,
                    "description": "Hilfstätigkeiten in der Schweißerei und im Metallbau.",
                },
            ],
            "educations": [
                {
                    "institution": "Technische Schule Hamburg",
                    "degree": "Ausbildung",
                    "field_of_study": "Zerspanungsmechaniker",
                    "start_date": date(2002, 9, 1),
                    "end_date": date(2005, 2, 28),
                },
            ],
            "skills": [
                ("CNC-Fräsen", "Fachkompetenz", "expert", 15),
                ("CNC-Drehen", "Fachkompetenz", "expert", 15),
                ("Siemens Sinumerik", "Software", "advanced", 8),
                ("Qualitätskontrolle", "Fachkompetenz", "advanced", 10),
                ("Schichtbetrieb", "Arbeitsmethodik", "expert", 20),
                ("ISO 9001", "Zertifizierung", "advanced", 5),
            ],
            "completeness": 91,
        },
        {
            "email": "greta.fleissig@quickwork.de",
            "full_name": "Greta Fleißig",
            "key": "Greta",
            "profile": {
                "headline": "Reinigungskraft (Minijob) – flexibel morgens",
                "summary": "Suche geringfügige Beschäftigung in der Gebäudereinigung. Morgendliche Zeiten bevorzugt. Zuverlässig und pünktlich.",
                "location": "Hamburg-Barmbek",
                "phone": "+49 175 1234005",
            },
            "experiences": [
                {
                    "company": "Privat (Haushaltsdienstleistungen)",
                    "title": "Reinigungskraft",
                    "start_date": date(2020, 1, 1),
                    "end_date": None,
                    "is_current": True,
                    "description": "Haushaltsreinigung für Privatpersonen auf Minijob-Basis.",
                },
            ],
            "educations": [],
            "skills": [
                ("Reinigung", "Fachkompetenz", "intermediate", 5),
                ("Deutsch", "Sprache", "expert", 0),
            ],
            "completeness": 55,
        },
        {
            "email": "lukas.frisch@quickwork.de",
            "full_name": "Lukas Frisch",
            "key": "Lukas",
            "profile": {
                "headline": "Berufseinsteiger Logistik – motiviert & lernbereit",
                "summary": (
                    "Frischer Berufsabschluss als Fachlagerist. Motiviert für meinen ersten "
                    "Vollzeitjob in der Logistik. Bereit für Schichtarbeit."
                ),
                "location": "Hamburg-Wandsbek",
                "phone": "+49 175 1234006",
            },
            "experiences": [
                {
                    "company": "Supermarkt Edeka Wandsbek",
                    "title": "Werkstudent Lager",
                    "start_date": date(2022, 9, 1),
                    "end_date": date(2025, 6, 30),
                    "is_current": False,
                    "description": "Warenwirtschaft, Auffüllen, Inventur – nebenbei während der Ausbildung.",
                },
            ],
            "educations": [
                {
                    "institution": "BBS Logistik Hamburg-Billstedt",
                    "degree": "Ausbildung",
                    "field_of_study": "Fachlagerist",
                    "start_date": date(2022, 9, 1),
                    "end_date": date(2025, 7, 31),
                },
            ],
            "skills": [
                ("Lagerlogistik", "Fachkompetenz", "beginner", 1),
                ("Staplerschein", "Zertifizierung", "beginner", 0),
                ("Teamarbeit", "Soft Skill", "intermediate", 3),
                ("Deutsch", "Sprache", "expert", 0),
            ],
            "completeness": 65,
        },
        {
            "email": "klara.stern@quickwork.de",
            "full_name": "Klara Stern",
            "key": "Klara",
            "profile": {
                "headline": "Qualitätsprüferin / Qualitätsmanagement",
                "summary": (
                    "Qualitätsfachkraft mit Erfahrung in Serienprüfung und Fehleranalyse. "
                    "Kenntnisse in SPC, FMEA und ISO 9001. Bereit für Schichteinsatz."
                ),
                "location": "Hamburg-Altona",
                "phone": "+49 175 1234007",
            },
            "experiences": [
                {
                    "company": "Airbus Operations GmbH",
                    "title": "Qualitätsprüferin Fertigung",
                    "start_date": date(2015, 4, 1),
                    "end_date": date(2025, 4, 30),
                    "is_current": False,
                    "description": "Sichtprüfung, Maßprüfung und Dokumentation nach Luftfahrtstandards (AS9100).",
                },
                {
                    "company": "TÜV Nord GmbH",
                    "title": "Prüftechnikerin",
                    "start_date": date(2011, 7, 1),
                    "end_date": date(2015, 3, 31),
                    "is_current": False,
                    "description": "Zerstörungsfreie Prüfung, Protokollierung nach DIN.",
                },
            ],
            "educations": [
                {
                    "institution": "Hochschule für Angewandte Wissenschaften Hamburg",
                    "degree": "Bachelor of Engineering",
                    "field_of_study": "Produktionstechnik",
                    "start_date": date(2007, 10, 1),
                    "end_date": date(2011, 6, 30),
                },
            ],
            "skills": [
                ("Qualitätsprüfung", "Fachkompetenz", "expert", 10),
                ("ISO 9001", "Zertifizierung", "expert", 8),
                ("FMEA", "Methodik", "advanced", 5),
                ("SPC", "Methodik", "intermediate", 3),
                ("AS9100", "Zertifizierung", "advanced", 7),
                ("Englisch", "Sprache", "advanced", 0),
            ],
            "completeness": 93,
        },
        {
            "email": "inge.hoffmann@quickwork.de",
            "full_name": "Inge Hoffmann",
            "key": "Inge",
            "profile": {
                "headline": "Objektleiterin Facility Management",
                "summary": (
                    "Erfahrene Objektleiterin mit Schwerpunkt Gebäudereinigung und "
                    "Facility Services. Führungserfahrung, Hygienemanagement-Zertifikat "
                    "vorhanden."
                ),
                "location": "Hamburg-Eimsbüttel",
                "phone": "+49 175 1234008",
            },
            "experiences": [
                {
                    "company": "Klüh Service Management GmbH",
                    "title": "Objektleiterin",
                    "start_date": date(2005, 2, 1),
                    "end_date": date(2025, 3, 31),
                    "is_current": False,
                    "description": "Leitung und Koordination von 12 Reinigungskräften in gewerblichen Objekten. Kundenkommunikation, Qualitätssicherung, Personalplanung.",
                },
                {
                    "company": "ISS Facility Services GmbH",
                    "title": "Reinigungskraft",
                    "start_date": date(1998, 6, 1),
                    "end_date": date(2005, 1, 31),
                    "is_current": False,
                    "description": "Unterhaltsreinigung in Büro- und Industriegebäuden.",
                },
            ],
            "educations": [
                {
                    "institution": "IHK Hamburg",
                    "degree": "Zertifikat",
                    "field_of_study": "Geprüfte Gebäudereiniger-Meisterin",
                    "start_date": date(2003, 1, 1),
                    "end_date": date(2004, 12, 31),
                },
            ],
            "skills": [
                ("Objektleitung", "Fachkompetenz", "expert", 20),
                ("Hygienemanagement", "Zertifizierung", "expert", 15),
                ("Personalführung", "Soft Skill", "advanced", 10),
                ("Gebäudereinigung", "Fachkompetenz", "expert", 25),
                ("Facility Management", "Fachkompetenz", "advanced", 10),
                ("DGUV Vorschrift 1", "Zertifizierung", "advanced", 5),
            ],
            "completeness": 89,
        },
    ]

    result = []
    for cd in candidates_data:
        row = await db.execute(select(User).where(User.email == cd["email"]))
        u = row.scalar_one_or_none()
        if not u:
            u = User(
                email=cd["email"],
                full_name=cd["full_name"],
                hashed_password=hash_password("Worker2025!"),
                role="candidate",  # ← KANDIDAT, noch kein Worker
                tenant_id=None,  # ← kein Tenant-Bezug als Kandidat
                is_active=True,
                is_verified=True,
            )
            db.add(u)
            await db.flush()
            db.add(
                PrivacyConsent(
                    user_id=u.id,
                    terms_accepted=True,
                    terms_accepted_at=datetime(2025, 8, 1),
                )
            )
            await db.flush()

        # Kandidatenprofil
        prof_row = await db.execute(
            select(CandidateProfile).where(CandidateProfile.user_id == u.id)
        )
        prof = prof_row.scalar_one_or_none()
        if not prof:
            pd = cd["profile"]
            prof = CandidateProfile(
                user_id=u.id,
                headline=pd.get("headline"),
                summary=pd.get("summary"),
                location=pd.get("location"),
                phone=pd.get("phone"),
                completeness_score=cd["completeness"],
            )
            db.add(prof)
            await db.flush()

            # Berufserfahrung
            for exp in cd["experiences"]:
                db.add(
                    WorkExperience(
                        profile_id=prof.id,
                        company=exp["company"],
                        title=exp["title"],
                        start_date=exp["start_date"],
                        end_date=exp.get("end_date"),
                        is_current=exp.get("is_current", False),
                        description=exp.get("description"),
                        source="manual",
                    )
                )

            # Ausbildung
            for edu in cd["educations"]:
                db.add(
                    Education(
                        profile_id=prof.id,
                        institution=edu["institution"],
                        degree=edu.get("degree"),
                        field_of_study=edu.get("field_of_study"),
                        start_date=edu.get("start_date"),
                        end_date=edu.get("end_date"),
                        source="manual",
                    )
                )

            # Skills
            for sname, scat, slevel, syears in cd["skills"]:
                db.add(
                    Skill(
                        profile_id=prof.id,
                        name=sname,
                        category=scat,
                        level=slevel,
                        years_of_experience=syears or None,
                        source="manual",
                    )
                )

            await db.flush()

        result.append((u, cd["key"]))
        print(f"   ✓ Kandidat: {cd['full_name']} – {cd['profile']['headline'][:50]}")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2.5 – Hiring-Prozess
# ─────────────────────────────────────────────────────────────────────────────


async def _seed_hiring_process(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    hr: dict,
    candidates: list[tuple],
) -> dict:
    """Simuliert den kompletten Bewerbungsfluss:

    Kandidat → bewirbt sich bei QuickWork → Screening-Anruf →
    Vorstellungsgespräch (terminiert + durchgeführt) → Scorecard → Offer/Eingestellt

    Gibt ein dict zurück: wkey → Application
    """

    max_r = hr["max"]
    lisa = hr["lisa"]

    # Application-Konfiguration pro Kandidat
    app_configs = {
        "Kalle": dict(
            position="Gabelstapler-Fahrer / Lager (Zeitarbeit)",
            company="QuickWork Personalservice GmbH",
            recruiter=max_r,
            applied=datetime(2025, 8, 15),
            screening=datetime(2025, 8, 20),
            interview_dt=datetime(2025, 9, 2, 10, 0),
            scorecard=dict(
                overall=5,
                technical=5,
                communication=4,
                motivation=5,
                recommendation="hire",
                notes="Sehr erfahren, Gabelstaplerschein vorhanden. Top-Kandidat für LogiPort.",
            ),
        ),
        "Mehmet": dict(
            position="Lagermitarbeiter / Kommissionierung (Zeitarbeit)",
            company="QuickWork Personalservice GmbH",
            recruiter=max_r,
            applied=datetime(2025, 8, 18),
            screening=datetime(2025, 8, 22),
            interview_dt=datetime(2025, 9, 3, 14, 0),
            scorecard=dict(
                overall=4,
                technical=4,
                communication=4,
                motivation=4,
                recommendation="hire",
                notes="Solide Erfahrung, flexibel in der Schicht. Gute Wahl.",
            ),
        ),
        "Sabrina": dict(
            position="Reinigungsfachkraft Teilzeit (Zeitarbeit)",
            company="QuickWork Personalservice GmbH",
            recruiter=lisa,
            applied=datetime(2025, 8, 20),
            screening=datetime(2025, 8, 26),
            interview_dt=datetime(2025, 9, 3, 10, 0),
            scorecard=dict(
                overall=4,
                technical=4,
                communication=5,
                motivation=4,
                recommendation="hire",
                notes="Zuverlässig, pünktlich. Für CityGlanz Teilzeit ideal.",
            ),
        ),
        "Bruno": dict(
            position="CNC-Maschinenführer (Zeitarbeit)",
            company="QuickWork Personalservice GmbH",
            recruiter=max_r,
            applied=datetime(2025, 8, 12),
            screening=datetime(2025, 8, 18),
            interview_dt=datetime(2025, 9, 1, 11, 0),
            scorecard=dict(
                overall=5,
                technical=5,
                communication=3,
                motivation=5,
                recommendation="hire",
                notes="15 Jahre CNC-Erfahrung. NordBeck-Anfrage passt perfekt.",
            ),
        ),
        "Greta": dict(
            position="Reinigungskraft Minijob",
            company="QuickWork Personalservice GmbH",
            recruiter=lisa,
            applied=datetime(2025, 10, 5),
            screening=datetime(2025, 10, 9),
            interview_dt=datetime(2025, 10, 13, 9, 0),
            scorecard=dict(
                overall=3,
                technical=3,
                communication=3,
                motivation=4,
                recommendation="hire",
                notes="Für Minijob-Stelle bei CityGlanz gut geeignet.",
            ),
        ),
        "Lukas": dict(
            position="Lagerhelfer / Kommissionierer (Zeitarbeit)",
            company="QuickWork Personalservice GmbH",
            recruiter=max_r,
            applied=datetime(2025, 11, 5),
            screening=datetime(2025, 11, 10),
            interview_dt=datetime(2025, 11, 14, 15, 0),
            scorecard=dict(
                overall=3,
                technical=3,
                communication=4,
                motivation=5,
                recommendation="hire",
                notes="Berufseinsteiger, aber sehr motiviert. LogiPort hat Kapazität.",
            ),
        ),
        "Klara": dict(
            position="Qualitätsprüferin / QM (Zeitarbeit)",
            company="QuickWork Personalservice GmbH",
            recruiter=max_r,
            applied=datetime(2025, 8, 10),
            screening=datetime(2025, 8, 15),
            interview_dt=datetime(2025, 8, 29, 13, 0),
            scorecard=dict(
                overall=5,
                technical=5,
                communication=4,
                motivation=5,
                recommendation="hire",
                notes="Top-Profil. NordBeck sucht genau diese Qualifikation.",
            ),
        ),
        "Inge": dict(
            position="Objektleiterin Gebäudereinigung (Zeitarbeit)",
            company="QuickWork Personalservice GmbH",
            recruiter=lisa,
            applied=datetime(2025, 8, 22),
            screening=datetime(2025, 8, 28),
            interview_dt=datetime(2025, 9, 5, 10, 0),
            scorecard=dict(
                overall=5,
                technical=5,
                communication=5,
                motivation=4,
                recommendation="hire",
                notes="Sehr erfahrene Objektleiterin. CityGlanz wird begeistert sein.",
            ),
        ),
    }

    result: dict = {}  # wkey → Application

    for user, wkey in candidates:
        cfg = app_configs.get(wkey)
        if not cfg:
            continue

        # Erstelle Application: Kandidat → QuickWork
        app = Application(
            user_id=user.id,
            company=cfg["company"],
            position=cfg["position"],
            source_platform="direct",
            status=ApplicationStatus.INTERVIEW,  # nach Interview, vor Offer
            applied_at=cfg["applied"],
        )
        db.add(app)
        await db.flush()

        # Application-History: applied → screening → interview
        history_steps = [
            (None, ApplicationStatus.APPLIED, cfg["applied"], "Bewerbung eingegangen"),
            (
                ApplicationStatus.APPLIED,
                ApplicationStatus.SCREENING,
                cfg["screening"],
                "Screening-Anruf vereinbart",
            ),
            (
                ApplicationStatus.SCREENING,
                ApplicationStatus.INTERVIEW,
                cfg["interview_dt"] - timedelta(days=3),
                "Vorstellungsgespräch terminiert",
            ),
        ]
        for from_s, to_s, changed_at, note in history_steps:
            db.add(
                ApplicationHistory(
                    application_id=app.id,
                    from_status=from_s,
                    to_status=to_s,
                    note=note,
                    changed_at=changed_at,
                )
            )

        # InterviewSchedule: Termin bestätigt und durchgeführt
        db.add(
            InterviewSchedule(
                application_id=app.id,
                proposed_by=cfg["recruiter"].id,
                tenant_id=tenant_id,
                scheduled_at=cfg["interview_dt"],
                status="confirmed",
                notes=(
                    f"Vorstellungsgespräch für {cfg['position']}. "
                    f"Recruiter: {cfg['recruiter'].full_name}"
                ),
            )
        )

        # InterviewScorecard: Bewertung nach dem Gespräch
        sc = cfg["scorecard"]
        db.add(
            InterviewScorecard(
                application_id=app.id,
                recruiter_id=cfg["recruiter"].id,
                tenant_id=tenant_id,
                overall_rating=sc["overall"],
                technical_rating=sc["technical"],
                communication_rating=sc["communication"],
                motivation_rating=sc["motivation"],
                recommendation=sc["recommendation"],
                notes=sc["notes"],
            )
        )

        await db.flush()
        result[wkey] = app

        stars = "★" * sc["overall"] + "☆" * (5 - sc["overall"])
        print(
            f"   ✓ {user.full_name}: Bewerbung → Interview → "
            f"{stars} ({sc['recommendation']}) – {cfg['recruiter'].full_name}"
        )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 – Einstellung als Zeitarbeiter
# ─────────────────────────────────────────────────────────────────────────────


async def _hire_as_workers(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    hr: dict,
    candidates: list[tuple],
    applications: dict,
) -> dict:
    """Setzt Application → 'offer' und aktiviert den Kandidaten als Worker.

    Entspricht dem Endpoint POST /zeitarbeit/workers/hire-from-application
    (hier direkt über die Models, da wir keinen HTTP-Server aufrufen können).
    """

    # Activation config per worker
    activation_config = {
        "Kalle": dict(employment_type="temp", hourly_rate=Decimal("16.50"), manager="max"),
        "Mehmet": dict(employment_type="temp", hourly_rate=Decimal("15.80"), manager="max"),
        "Sabrina": dict(employment_type="parttime", hourly_rate=Decimal("14.50"), manager="lisa"),
        "Bruno": dict(employment_type="fulltime", hourly_rate=Decimal("17.00"), manager="max"),
        "Greta": dict(employment_type="minijob", hourly_rate=Decimal("13.80"), manager="lisa"),
        "Lukas": dict(employment_type="temp", hourly_rate=Decimal("14.00"), manager="lisa"),
        "Klara": dict(employment_type="fulltime", hourly_rate=Decimal("16.00"), manager="max"),
        "Inge": dict(employment_type="temp", hourly_rate=Decimal("15.50"), manager="lisa"),
    }

    worker_profiles = {
        "Kalle": dict(
            street="Billwerder Neuer Deich 5",
            city="Hamburg",
            zip="20539",
            dob=date(1985, 3, 12),
            iban="DE89200505501234567800",
        ),
        "Mehmet": dict(
            street="Rothenburgsort 18",
            city="Hamburg",
            zip="20539",
            dob=date(1990, 7, 22),
            iban="DE89200505501234567801",
        ),
        "Sabrina": dict(
            street="Hammerbrook 7",
            city="Hamburg",
            zip="20097",
            dob=date(1993, 11, 5),
            iban="DE89200505501234567802",
        ),
        "Bruno": dict(
            street="Veddel 3",
            city="Hamburg",
            zip="20539",
            dob=date(1978, 6, 30),
            iban="DE89200505501234567803",
        ),
        "Greta": dict(
            street="Barmbek-Nord 22",
            city="Hamburg",
            zip="22303",
            dob=date(1995, 2, 14),
            iban="DE89200505501234567804",
        ),
        "Lukas": dict(
            street="Wandsbek Markt 11",
            city="Hamburg",
            zip="22041",
            dob=date(2000, 9, 8),
            iban="DE89200505501234567805",
        ),
        "Klara": dict(
            street="Altona-Altstadt 9",
            city="Hamburg",
            zip="22765",
            dob=date(1988, 4, 18),
            iban="DE89200505501234567806",
        ),
        "Inge": dict(
            street="Eimsbüttel 44",
            city="Hamburg",
            zip="20257",
            dob=date(1970, 12, 3),
            iban="DE89200505501234567807",
        ),
    }

    activation_dates = {
        "Kalle": datetime(2025, 9, 3, 9, 0),
        "Bruno": datetime(2025, 9, 3, 10, 0),
        "Klara": datetime(2025, 9, 3, 11, 0),
        "Mehmet": datetime(2025, 9, 5, 9, 0),
        "Sabrina": datetime(2025, 9, 5, 14, 0),
        "Inge": datetime(2025, 9, 8, 10, 0),
        "Greta": datetime(2025, 10, 15, 9, 0),
        "Lukas": datetime(2025, 11, 17, 9, 0),
    }

    result: dict = {}

    for user, wkey in candidates:
        cfg = activation_config.get(wkey, {})
        prof = worker_profiles.get(wkey, {})
        act_date = activation_dates.get(wkey, datetime(2025, 9, 1))
        manager_key = cfg.get("manager", "max")
        recruiter = hr[manager_key]

        # Check already activated
        ws_row = await db.execute(select(WorkerSettings).where(WorkerSettings.user_id == user.id))
        if ws_row.scalar_one_or_none():
            result[wkey] = user
            continue

        # ── Advance Application: interview → offer (= Eingestellt) ──────
        app = applications.get(wkey)
        if app:
            app.status = ApplicationStatus.OFFER
            db.add(
                ApplicationHistory(
                    application_id=app.id,
                    from_status=ApplicationStatus.INTERVIEW,
                    to_status=ApplicationStatus.OFFER,
                    note=(
                        f"Als Zeitarbeiter eingestellt durch {recruiter.full_name}. "
                        f"Einsatz ab {act_date.strftime('%d.%m.%Y')}."
                    ),
                )
            )

        # ── Worker-Aktivierung (= POST /zeitarbeit/workers/hire-from-application) ──
        user.role = "worker"
        user.tenant_id = tenant_id

        ws = WorkerSettings(
            user_id=user.id,
            tenant_id=tenant_id,
            is_active=True,
            employment_type=cfg.get("employment_type", "temp"),
            max_weekly_hours=40 if cfg.get("employment_type") in ("fulltime", "temp") else 20,
            hourly_rate=cfg.get("hourly_rate"),
            active_modules=dict(ALL_MODULES),
            assigned_manager_id=recruiter.id,
            activated_at=act_date,
            phone=prof.get("phone"),
            address_street=prof.get("street"),
            address_city=prof.get("city"),
            address_zip=prof.get("zip"),
            address_country="DE",
            date_of_birth=prof.get("dob"),
            iban=prof.get("iban"),
        )
        db.add(ws)
        await db.flush()

        result[wkey] = user
        print(
            f"   ✓ Eingestellt: {user.full_name} "
            f"({cfg.get('employment_type')} | {cfg.get('hourly_rate')} €/h) "
            f"am {act_date.strftime('%d.%m.%Y')}"
        )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4 – Operativdaten
# ─────────────────────────────────────────────────────────────────────────────


async def _seed_customers(db: AsyncSession, tenant_id: uuid.UUID) -> dict:

    print("🏭 Kundenfirmen …")

    data = [
        (
            "LogiPort GmbH",
            "logiport",
            "Logistik & Lagerwirtschaft – Hamburger Hafen, Terminal 7",
            "Hamburg",
        ),
        (
            "NordBeck GmbH",
            "nordbeck",
            "Produktion & Fertigung – Harburger Schloßstraße 6",
            "Hamburg-Harburg",
        ),
        (
            "CityGlanz Services GmbH",
            "cityglanz",
            "Gebäudereinigung & Facility – Mönckebergstraße 12",
            "Hamburg",
        ),
    ]

    result: dict = {}
    for name, key, description, location in data:
        row = await db.execute(select(Company).where(Company.name == name))
        c = row.scalar_one_or_none()
        if not c:
            c = Company(name=name, description=description, location=location)
            db.add(c)
            await db.flush()
        result[key] = c
        print(f"   ✓ {name}")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Einsätze (WorkAssignment) mit Slots + Dispositions
# ─────────────────────────────────────────────────────────────────────────────


async def _seed_einsaetze(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    workers: dict,
    customers: dict,
    hr: dict,
) -> None:
    """Erstellt WorkAssignment-Einsätze mit 2–4 Plätzen (slots) und verteilt
    Zeitarbeiter via Disposition darauf. Simuliert die Auftragssteuerung."""

    print("🏗️  Einsätze + Dispositions …")

    max_r = hr["max"]
    lisa = hr["lisa"]
    jana = hr["jana"]

    # Einsatz-Definitionen: (key, company_key, recruiter, title, skills, slots, start, end, shift, rate, status)
    einsatz_data = [
        dict(
            key="logiport_lager",
            company=customers["logiport"],
            recruiter=max_r,
            title="Lager & Umschlag – LogiPort Terminal 7",
            description=(
                "Gabelstapler- und Lagerarbeiten im Containerumschlag. "
                "Mehrere Plätze für Früh- und Spätschicht."
            ),
            skills=["Gabelstapler BGG 925", "Lagerwirtschaft", "Schwergutverlad"],
            slots=3,
            start_date=date(2025, 10, 1),
            end_date=date(2026, 3, 31),
            shift="day",
            hourly_rate=Decimal("16.00"),
            status="active",
            workers_placed=[
                dict(
                    wkey="Kalle",
                    score=Decimal("0.9800"),
                    skills=["Gabelstapler BGG 925", "Lagerwirtschaft"],
                    missing=[],
                    started=date(2025, 10, 1),
                    status="placed",
                ),
                dict(
                    wkey="Mehmet",
                    score=Decimal("0.8500"),
                    skills=["Lagerwirtschaft"],
                    missing=["Gabelstapler BGG 925"],
                    started=date(2025, 10, 1),
                    status="placed",
                ),
                dict(
                    wkey="Lukas",
                    score=Decimal("0.7200"),
                    skills=["Lagerwirtschaft"],
                    missing=["Gabelstapler BGG 925"],
                    started=date(2025, 12, 1),
                    status="placed",
                ),
            ],
        ),
        dict(
            key="nordbeck_produktion",
            company=customers["nordbeck"],
            recruiter=max_r,
            title="CNC-Produktion & Qualitätssicherung – NordBeck",
            description=(
                "Maschinenführer und QM-Fachkräfte für die CNC-Fertigung. "
                "Qualifiziertes Personal mit technischem Hintergrund."
            ),
            skills=["CNC-Fräsen", "Qualitätsprüfung", "ISO 9001", "Messmittelkunde"],
            slots=3,
            start_date=date(2025, 10, 1),
            end_date=date(2026, 3, 31),
            shift="flexible",
            hourly_rate=Decimal("16.50"),
            status="active",
            workers_placed=[
                dict(
                    wkey="Bruno",
                    score=Decimal("0.9500"),
                    skills=["CNC-Fräsen"],
                    missing=["Qualitätsprüfung"],
                    started=date(2025, 10, 1),
                    status="placed",
                ),
                dict(
                    wkey="Klara",
                    score=Decimal("0.9700"),
                    skills=["Qualitätsprüfung", "ISO 9001", "Messmittelkunde"],
                    missing=[],
                    started=date(2025, 10, 1),
                    status="placed",
                ),
                # 1 offener Platz → suggested candidate
                dict(
                    wkey="Mehmet",
                    score=Decimal("0.6000"),
                    skills=["Lagerwirtschaft"],
                    missing=["CNC-Fräsen", "Qualitätsprüfung"],
                    started=None,
                    status="suggested",
                ),
            ],
        ),
        dict(
            key="cityglanz_reinigung",
            company=customers["cityglanz"],
            recruiter=lisa,
            title="Gebäudereinigung & Facility Management – CityGlanz",
            description=(
                "Unterhalts- und Büroreinigung für Hamburger Innenstadt-Objekte. "
                "Teilzeit- und Minijob-Stellen, flexible Schichtzeiten morgens."
            ),
            skills=["Gebäudereinigung", "HACCP", "Reinigungsmaschinen"],
            slots=4,
            start_date=date(2025, 10, 1),
            end_date=date(2026, 3, 31),
            shift="day",
            hourly_rate=Decimal("14.00"),
            status="active",
            workers_placed=[
                dict(
                    wkey="Sabrina",
                    score=Decimal("0.9200"),
                    skills=["Gebäudereinigung", "HACCP"],
                    missing=[],
                    started=date(2025, 10, 1),
                    status="placed",
                ),
                dict(
                    wkey="Greta",
                    score=Decimal("0.8000"),
                    skills=["Gebäudereinigung"],
                    missing=["HACCP"],
                    started=date(2025, 11, 1),
                    status="placed",
                ),
                dict(
                    wkey="Inge",
                    score=Decimal("0.9600"),
                    skills=["Gebäudereinigung", "HACCP", "Reinigungsmaschinen"],
                    missing=[],
                    started=date(2025, 10, 1),
                    status="placed",
                ),
                # 1 offener Platz
            ],
        ),
        dict(
            key="nordbeck_erweiterung",
            company=customers["nordbeck"],
            recruiter=jana,
            title="Produktionsmitarbeiter Montage – NordBeck (Erweiterung)",
            description=(
                "Neue Montage-Linie ab Q1 2026. Flexibler Einsatz, "
                "Einarbeitung durch NordBeck-Schichtleitung."
            ),
            skills=["Montage", "Qualitätsprüfung"],
            slots=2,
            start_date=date(2026, 3, 3),
            end_date=date(2026, 6, 30),
            shift="day",
            hourly_rate=Decimal("15.50"),
            status="confirmed",
            workers_placed=[
                dict(
                    wkey="Mehmet",
                    score=Decimal("0.7800"),
                    skills=["Lagerwirtschaft"],
                    missing=["Montage"],
                    started=date(2026, 3, 3),
                    status="placed",
                ),
                # 1 offener Platz → in Planung
            ],
        ),
    ]

    for ez in einsatz_data:
        # Prüfen ob bereits vorhanden
        existing = await db.execute(
            select(WorkAssignment).where(
                WorkAssignment.title == ez["title"],
                WorkAssignment.tenant_id == tenant_id,
            )
        )
        wa = existing.scalar_one_or_none()
        if not wa:
            wa = WorkAssignment(
                recruiter_id=ez["recruiter"].id,
                company_id=ez["company"].id,
                tenant_id=tenant_id,
                title=ez["title"],
                description=ez["description"],
                required_skills=ez["skills"],
                slots=ez["slots"],
                start_date=ez["start_date"],
                end_date=ez["end_date"],
                shift=ez["shift"],
                hourly_rate=ez["hourly_rate"],
                status=ez["status"],
            )
            db.add(wa)
            await db.flush()

        placed = sum(1 for w in ez["workers_placed"] if w["status"] == "placed")
        print(f"   ✓ {ez['title']} – {ez['slots']} Plätze ({placed} besetzt)")

        for wp in ez["workers_placed"]:
            worker = workers.get(wp["wkey"])
            if not worker:
                continue
            # Idempotenz
            exists = await db.execute(
                select(Disposition).where(
                    Disposition.assignment_id == wa.id,
                    Disposition.worker_id == worker.id,
                )
            )
            if exists.scalar_one_or_none():
                continue
            db.add(
                Disposition(
                    assignment_id=wa.id,
                    worker_id=worker.id,
                    score=wp["score"],
                    matched_skills=wp["skills"],
                    missing_skills=wp["missing"],
                    status=wp["status"],
                    started_at=wp["started"],
                    ended_at=None,
                    notes=None,
                )
            )

        await db.flush()

    await db.commit()


async def _seed_assignments(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    workers: dict,
    customers: dict,
    hr: dict,
) -> dict:

    admin = hr["admin"]
    print("📅 Einsatzplan (Okt 2025 – Mär 2026) …")

    plans = [
        (
            "Kalle",
            "logiport",
            date(2025, 10, 1),
            date(2026, 3, 31),
            time(6, 0),
            time(14, 30),
            "Gabelstapler-Fahrer Wareneingang",
            "active",
        ),
        (
            "Mehmet",
            "logiport",
            date(2025, 10, 1),
            date(2026, 2, 28),
            time(14, 0),
            time(22, 30),
            "Lagermitarbeiter Schicht B",
            "completed",
        ),
        (
            "Mehmet",
            "nordbeck",
            date(2026, 3, 3),
            date(2026, 6, 30),
            time(6, 30),
            time(15, 0),
            "Produktionsmitarbeiter Montage",
            "confirmed",
        ),
        (
            "Sabrina",
            "cityglanz",
            date(2025, 10, 1),
            date(2026, 3, 31),
            time(7, 0),
            time(13, 0),
            "Büroreinigung Innenstadt",
            "active",
        ),
        (
            "Bruno",
            "nordbeck",
            date(2025, 10, 1),
            date(2026, 3, 31),
            time(6, 0),
            time(14, 30),
            "Maschinenführer CNC",
            "active",
        ),
        (
            "Greta",
            "cityglanz",
            date(2025, 11, 1),
            date(2026, 3, 31),
            time(8, 0),
            time(12, 0),
            "Unterhaltsreinigung HafenCity",
            "active",
        ),
        (
            "Lukas",
            "logiport",
            date(2025, 12, 1),
            date(2026, 3, 31),
            time(6, 0),
            time(14, 30),
            "Kommissionierer",
            "active",
        ),
        (
            "Klara",
            "nordbeck",
            date(2025, 10, 1),
            date(2026, 3, 31),
            time(14, 0),
            time(22, 30),
            "Qualitätsprüferin",
            "active",
        ),
        (
            "Inge",
            "cityglanz",
            date(2025, 10, 1),
            date(2026, 3, 31),
            time(6, 0),
            time(14, 0),
            "Objektleiterin Reinigung",
            "active",
        ),
    ]

    by_worker: dict = {}
    for wkey, ckey, start, end, sh_s, sh_e, role, status in plans:
        worker = workers.get(wkey)
        if not worker:
            continue
        customer = customers[ckey]
        a = WorkerAssignment(
            worker_id=worker.id,
            tenant_id=tenant_id,
            created_by=admin.id,
            start_date=start,
            end_date=end,
            shift_start=sh_s,
            shift_end=sh_e,
            customer_company=customer.name,
            location=customer.location,
            role_description=role,
            status=status,
        )
        db.add(a)
        await db.flush()
        by_worker.setdefault(wkey, []).append(a)
        print(f"   ✓ {wkey} → {customer.name} ({start} – {end})")

    return by_worker


async def _seed_time_entries(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    workers: dict,
    assignments: dict,
    hr: dict,
) -> None:

    admin = hr["admin"]
    print("⏱  Zeiteinträge (Okt 2025 – Mär 2026) …")

    shifts = {
        "Kalle": (6, 0, 14, 30, 30),
        "Mehmet": (14, 0, 22, 30, 30),
        "Sabrina": (7, 0, 13, 0, 0),
        "Bruno": (6, 0, 14, 30, 30),
        "Greta": (8, 0, 12, 0, 0),
        "Lukas": (6, 0, 14, 30, 30),
        "Klara": (14, 0, 22, 30, 30),
        "Inge": (6, 0, 14, 0, 30),
    }

    approved_months = [(2025, 10), (2025, 11), (2025, 12), (2026, 1), (2026, 2)]
    pending_months = [(2026, 3)]

    total = 0
    for wkey, worker in workers.items():
        si = shifts.get(wkey)
        if not si:
            continue
        ci_h, ci_m, co_h, co_m, brk = si

        assign_list = assignments.get(wkey, [])
        if not assign_list:
            continue
        first_start = min(a.start_date for a in assign_list)

        for y, m in approved_months + pending_months:
            if date(y, m, 1) < first_start:
                continue

            is_approved = (y, m) in approved_months
            status = "approved" if is_approved else "submitted"
            approved_by = admin.id if is_approved else None
            approved_at = (
                (datetime(y, m if m < 12 else 1, 1) + timedelta(days=32)) if is_approved else None
            )

            for d in _workdays(y, m):
                if d < first_start:
                    continue
                db.add(
                    TimeEntry(
                        worker_id=worker.id,
                        tenant_id=tenant_id,
                        entry_date=d,
                        clock_in=_dt(d, ci_h, ci_m),
                        clock_out=_dt(d, co_h, co_m),
                        break_minutes=brk,
                        status=status,
                        approved_by=approved_by,
                        approved_at=approved_at,
                        location_note="Einsatzbetrieb",
                    )
                )
                total += 1

            if total % 200 == 0:
                await db.flush()

    await db.flush()
    print(f"   ✓ {total} Zeiteinträge")


async def _seed_absences(db: AsyncSession, tenant_id: uuid.UUID, workers: dict, hr: dict) -> None:
    admin = hr["admin"]
    from app.absences.models import calc_working_days

    print("🏖  Abwesenheiten …")

    data = [
        ("Klara", "vacation", date(2025, 12, 23), date(2026, 1, 3), "approved", "Weihnachtsurlaub"),
        ("Bruno", "sick", date(2026, 1, 13), date(2026, 1, 17), "approved", "Grippe"),
        ("Sabrina", "vacation", date(2026, 2, 16), date(2026, 2, 27), "approved", "Winterurlaub"),
        ("Greta", "vacation", date(2026, 4, 6), date(2026, 4, 17), "pending", "Osterurlaub"),
        ("Lukas", "other", date(2026, 3, 18), date(2026, 3, 18), "approved", "Arzttermin"),
        ("Inge", "special", date(2026, 2, 9), date(2026, 2, 9), "approved", "Beerdigung"),
    ]

    for wkey, atype, start, end, status, note in data:
        worker = workers.get(wkey)
        if not worker:
            continue
        reviewed_at = (
            datetime(end.year, end.month, end.day, 10, 0) if status == "approved" else None
        )
        db.add(
            Absence(
                worker_id=worker.id,
                tenant_id=tenant_id,
                absence_type=atype,
                start_date=start,
                end_date=end,
                working_days=calc_working_days(start, end),
                worker_note=note,
                status=status,
                reviewed_by=admin.id if status == "approved" else None,
                reviewed_at=reviewed_at,
                reviewer_note="Genehmigt." if status == "approved" else None,
                certificate_uploaded=(atype == "sick"),
            )
        )
        print(f"   ✓ {wkey}: {atype} {start} – {end}")

    await db.flush()


async def _seed_paystubs(db: AsyncSession, tenant_id: uuid.UUID, workers: dict, hr: dict) -> None:

    admin = hr["admin"]
    print("💰 Gehaltszettel …")

    monthly_hours = {
        "Kalle": 168,
        "Mehmet": 168,
        "Sabrina": 96,
        "Bruno": 168,
        "Greta": 80,
        "Lukas": 168,
        "Klara": 168,
        "Inge": 160,
    }
    hourly_rates_cents = {
        "Kalle": 1650,
        "Mehmet": 1580,
        "Sabrina": 1450,
        "Bruno": 1700,
        "Greta": 1380,
        "Lukas": 1400,
        "Klara": 1600,
        "Inge": 1550,
    }
    first_month = {  # earliest month to create stubs for
        "Kalle": (2025, 10),
        "Mehmet": (2025, 10),
        "Sabrina": (2025, 10),
        "Bruno": (2025, 10),
        "Greta": (2025, 11),
        "Lukas": (2025, 12),
        "Klara": (2025, 10),
        "Inge": (2025, 10),
    }

    published = [(2025, 10), (2025, 11), (2025, 12), (2026, 1), (2026, 2)]
    draft = [(2026, 3)]

    for wkey, worker in workers.items():
        rate = hourly_rates_cents[wkey]
        h = monthly_hours[wkey]
        fm = first_month[wkey]

        for y, m in published + draft:
            if (y, m) < fm:
                continue

            gross = (rate * h) // 100
            tax = int(gross * 0.19)
            sv = int(gross * 0.20)
            net = gross - tax - sv

            status = "published" if (y, m) in published else "draft"
            pub_at = datetime(y, m, 28, 12, 0) if status == "published" else None

            doc_url = None
            if status == "published":
                month_str = f"{y}-{m:02d}"
                pdf_id = str(uuid.uuid4())
                pdf = gen_lohnzettel(worker.full_name, month_str, gross, net, h, pdf_id)
                doc_url, _ = _save_pdf(f"lohnzettel_{wkey.lower()}_{month_str}.pdf", pdf)

            db.add(
                PayStub(
                    tenant_id=tenant_id,
                    worker_id=worker.id,
                    created_by=admin.id,
                    period_year=y,
                    period_month=m,
                    gross_cents=gross,
                    net_cents=net,
                    tax_cents=tax,
                    social_security_cents=sv,
                    hours_worked=Decimal(str(h)),
                    overtime_hours=Decimal("0"),
                    document_url=doc_url,
                    status=status,
                    published_at=pub_at,
                )
            )

    await db.flush()
    print("   ✓ Gehaltszettel für alle Worker (Okt 2025 – Mär 2026)")


async def _seed_equipment(db: AsyncSession, tenant_id: uuid.UUID, workers: dict, hr: dict) -> None:

    admin = hr["admin"]
    print("🦺 Equipment …")

    items = [
        ("Sicherheitsschuhe S3 – Kalle Brenner", "clothing", "SCH-001", "good"),
        ("Schutzhelm – Kalle Brenner", "other", "HEL-001", "good"),
        ("Warnweste – Mehmet Demir", "clothing", "WAR-001", "good"),
        ("Laptop Lenovo ThinkPad – Klara Stern", "laptop", "LAP-001", "good"),
        ("Reinigungsgerät Kärcher – Inge Hoffmann", "tools", "REI-001", "fair"),
        ("Sicherheitsschuhe S3 – Bruno Bergmann", "clothing", "SCH-002", "good"),
        ("Arbeitshandschuhe – Bruno Bergmann", "other", "HAN-001", "good"),
    ]
    assignments = [
        ("SCH-001", "Kalle", date(2025, 10, 1)),
        ("HEL-001", "Kalle", date(2025, 10, 1)),
        ("WAR-001", "Mehmet", date(2025, 10, 1)),
        ("LAP-001", "Klara", date(2025, 10, 1)),
        ("REI-001", "Inge", date(2025, 10, 1)),
        ("SCH-002", "Bruno", date(2025, 10, 1)),
        ("HAN-001", "Bruno", date(2025, 10, 1)),
    ]

    items_map: dict = {}
    for name, cat, serial, cond in items:
        item = EquipmentItem(
            tenant_id=tenant_id,
            name=name,
            category=cat,
            serial_number=serial,
            condition=cond,
            status="assigned",
        )
        db.add(item)
        await db.flush()
        items_map[serial] = item

    for serial, wkey, assigned_at in assignments:
        w = workers.get(wkey)
        item = items_map.get(serial)
        if not w or not item:
            continue
        db.add(
            EquipmentAssignment(
                equipment_item_id=item.id,
                worker_id=w.id,
                tenant_id=tenant_id,
                assigned_by=admin.id,
                assigned_at=assigned_at,
                notes="Ausgabe bei Einsatzbeginn",
            )
        )

    await db.flush()
    print(f"   ✓ {len(items)} Artikel, {len(assignments)} Zuweisungen")


async def _seed_tasks(db: AsyncSession, tenant_id: uuid.UUID, workers: dict, hr: dict) -> None:

    print("✅ Tasks …")

    max_r = hr["max"]
    lisa = hr["lisa"]
    data = [
        (
            "Kalle",
            max_r,
            "Gabelstaplerschein erneuern (fällig!)",
            "Der Befähigungsnachweis läuft 31.03.2026 ab. DEKRA-Termin bis 15.03.2026 beauftragen.",
            date(2026, 3, 15),
            "urgent",
            "open",
        ),
        (
            "Kalle",
            max_r,
            "Wiederholungsunterweisung LogiPort Q1/2026",
            "Jährliche Sicherheitsunterweisung abschließen.",
            date(2026, 3, 31),
            "high",
            "in_progress",
        ),
        (
            "Bruno",
            max_r,
            "Maschinenbediener-Schulung NordBeck CNC-5",
            "Schulung für neue CNC-Maschine am 10.02.2026.",
            date(2026, 2, 10),
            "medium",
            "done",
        ),
        (
            "Klara",
            lisa,
            "Personalfragebogen aktualisieren",
            "Neue Adresse und IBAN: bitte Fragebogen neu ausfüllen.",
            date(2026, 3, 20),
            "medium",
            "open",
        ),
        (
            "Inge",
            lisa,
            "Zertifikat Hygienemanagement einreichen",
            "Für CityGlanz-Vertrag benötigt.",
            date(2026, 4, 1),
            "high",
            "open",
        ),
        (
            "Sabrina",
            lisa,
            "Urlaubsantrag Feb – Rückkehrtermin bestätigen",
            "Rückkehrdatum 28.02.2026 bestätigen.",
            date(2026, 2, 20),
            "low",
            "done",
        ),
        (
            "Lukas",
            max_r,
            "Einarbeitung LogiPort abschließen",
            "3-tägige Einarbeitung – Abzeichnung durch Schichtleiter anfordern.",
            date(2025, 12, 15),
            "medium",
            "done",
        ),
        (
            "Mehmet",
            max_r,
            "Einsatzbeschreibung NordBeck lesen und bestätigen",
            "Vor Einsatzbeginn 03.03.2026 lesen und im Portal bestätigen.",
            date(2026, 3, 1),
            "high",
            "open",
        ),
    ]

    for wkey, assigner, title, desc, due, prio, status in data:
        w = workers.get(wkey)
        if not w:
            continue
        completed_at = datetime(due.year, due.month, due.day, 14, 0) if status == "done" else None
        db.add(
            Task(
                tenant_id=tenant_id,
                assigned_to=w.id,
                assigned_by=assigner.id,
                title=title,
                description=desc,
                due_date=due,
                priority=prio,
                status=status,
                completed_at=completed_at,
            )
        )
        print(f"   ✓ {title[:55]}…" if len(title) > 55 else f"   ✓ {title}")

    await db.flush()


async def _seed_messages(db: AsyncSession, tenant_id: uuid.UUID, workers: dict, hr: dict) -> None:

    print("💬 Nachrichten …")

    max_r = hr["max"]
    lisa = hr["lisa"]
    now = datetime.now()

    threads = [
        {
            "wkey": "Kalle",
            "claimed_by": max_r,
            "status": "in_progress",
            "subject": "Gabelstaplerschein – Verlängerung bis wann?",
            "msgs": [
                (
                    "Kalle",
                    False,
                    "Hallo Herr Müller, mein Gabelstaplerschein läuft Ende März aus. Wie ist die Vorgehensweise für die Verlängerung?",
                ),
                (
                    "max_r",
                    False,
                    "Kein Problem! Ich habe dir einen Task im Portal angelegt. Ruf bitte DEKRA an und vereinbare einen Termin – Kosten übernehmen wir.",
                ),
                ("Kalle", False, "Verstanden. Gibt es einen Ansprechpartner bei DEKRA?"),
                (
                    "max_r",
                    False,
                    "Ansprechpartner: Frau Schmidt, +49 40 3456 0. QuickWork als Auftraggeber angeben.",
                ),
                (
                    "max_r",
                    True,
                    "INTERN: Kalle hat noch keine Terminbestätigung gesendet – ggf. nachfassen.",
                ),
            ],
        },
        {
            "wkey": "Bruno",
            "claimed_by": max_r,
            "status": "resolved",
            "subject": "Krankmeldung 13.–17. Januar",
            "msgs": [
                ("Bruno", False, "Guten Morgen, ich bin krank – Grippe. AU liegt vor."),
                (
                    "max_r",
                    False,
                    "Gute Besserung! NordBeck ist informiert. Bitte AU per Post oder Portal-Upload.",
                ),
                ("Bruno", False, "AU habe ich hochgeladen. Melde mich wenn ich wieder fit bin."),
                ("max_r", False, "Super, erhalten. Bleib gesund!"),
            ],
        },
        {
            "wkey": "Sabrina",
            "claimed_by": None,
            "status": "open",
            "subject": "Urlaubsantrag Februar – Bestätigung ausstehend",
            "msgs": [
                (
                    "Sabrina",
                    False,
                    "Ich habe einen Urlaubsantrag für 16.–27. Feb. eingereicht. Wann kommt Rückmeldung?",
                ),
                (
                    "lisa",
                    False,
                    "Hallo Sabrina, wir prüfen das mit CityGlanz und melden uns bis Freitag.",
                ),
                ("Sabrina", False, "Danke, ich warte auf eure Nachricht."),
            ],
        },
        {
            "wkey": "Lukas",
            "claimed_by": max_r,
            "status": "resolved",
            "subject": "Erste Woche bei LogiPort – Feedback",
            "msgs": [
                (
                    "Lukas",
                    False,
                    "Hallo Max, wollte kurz Feedback geben – die ersten zwei Tage liefen super! Team ist nett.",
                ),
                (
                    "max_r",
                    False,
                    "Das freut mich! Herr Koch hat sich auch positiv gemeldet. Weiter so!",
                ),
            ],
        },
    ]

    sender_map = {
        "max_r": max_r,
        "lisa": lisa,
    }

    for td in threads:
        wkey = td["wkey"]
        worker = workers.get(wkey)
        if not worker:
            continue
        sender_map[wkey] = worker

        created_at = now - timedelta(days=len(td["msgs"]) * 2 + 5)
        thread = MessageThread(
            tenant_id=tenant_id,
            worker_id=worker.id,
            claimed_by=td["claimed_by"].id if td["claimed_by"] else None,
            subject=td["subject"],
            status=td["status"],
            last_message_at=now - timedelta(days=1),
            unread_hr=1 if td["status"] == "open" else 0,
            unread_worker=0,
            created_at=created_at,
            updated_at=created_at,
        )
        db.add(thread)
        await db.flush()

        for i, (sender_key, is_internal, body) in enumerate(td["msgs"]):
            sender = sender_map.get(sender_key)
            if not sender:
                continue
            db.add(
                Message(
                    thread_id=thread.id,
                    sender_id=sender.id,
                    body=body,
                    is_internal_note=is_internal,
                    created_at=created_at + timedelta(hours=i * 4 + 1),
                )
            )

        print(f"   ✓ {td['subject'][:55]} ({td['status']})")

    await db.flush()


async def _seed_documents(db: AsyncSession, tenant_id: uuid.UUID, workers: dict, hr: dict) -> None:

    admin = hr["admin"]
    print("📄 DMS-Dokumente (PDFs) …")

    # Ensure categories exist
    cat_defs = [
        ("vertraege", "Verträge", "#059669", "📋"),
        ("qualifikationen", "Qualifikationen", "#2563eb", "🎓"),
        ("unterweisungen", "Unterweisungen", "#d97706", "🦺"),
        ("personalunterlagen", "Personalunterlagen", "#7c3aed", "📁"),
    ]
    cat_map: dict = {}
    for i, (slug, name, color, icon) in enumerate(cat_defs):
        row = await db.execute(
            select(DocCategory).where(
                DocCategory.slug == slug,
                DocCategory.tenant_id == tenant_id,
            )
        )
        cat = row.scalar_one_or_none()
        if not cat:
            cat = DocCategory(
                tenant_id=tenant_id,
                name=name,
                slug=slug,
                color=color,
                icon=icon,
                sort_order=i,
            )
            db.add(cat)
            await db.flush()
        cat_map[slug] = cat.id

    # Worker → docs
    worker_meta = {
        "Kalle": (
            "LogiPort GmbH",
            "Gabelstapler-Fahrer",
            "12.03.1985",
            "Billwerder Neuer Deich 5, 20539 Hamburg",
            "DE89200505501234567800",
        ),
        "Mehmet": (
            "LogiPort GmbH",
            "Lagermitarbeiter",
            "22.07.1990",
            "Rothenburgsort 18, 20539 Hamburg",
            "DE89200505501234567801",
        ),
        "Sabrina": (
            "CityGlanz Services GmbH",
            "Büroreinigung",
            "05.11.1993",
            "Hammerbrook 7, 20097 Hamburg",
            "DE89200505501234567802",
        ),
        "Bruno": (
            "NordBeck GmbH",
            "Maschinenführer CNC",
            "30.06.1978",
            "Veddel 3, 20539 Hamburg",
            "DE89200505501234567803",
        ),
        "Klara": (
            "NordBeck GmbH",
            "Qualitätsprüferin",
            "18.04.1988",
            "Altona-Altstadt 9, 22765 Hamburg",
            "DE89200505501234567806",
        ),
        "Inge": (
            "CityGlanz Services GmbH",
            "Objektleiterin",
            "03.12.1970",
            "Eimsbüttel 44, 20257 Hamburg",
            "DE89200505501234567807",
        ),
        "Lukas": (
            "LogiPort GmbH",
            "Kommissionierer",
            "08.09.2000",
            "Wandsbek Markt 11, 22041 Hamburg",
            "DE89200505501234567805",
        ),
        "Greta": (
            "CityGlanz Services GmbH",
            "Unterhaltsreinigung",
            "14.02.1995",
            "Barmbek-Nord 22, 22303 Hamburg",
            "DE89200505501234567804",
        ),
    }

    doc_plan = {
        "Kalle": [
            ("av", "vertraege"),
            ("gs", "qualifikationen"),
            ("su", "unterweisungen"),
            ("pf", "personalunterlagen"),
        ],
        "Mehmet": [("av", "vertraege"), ("su", "unterweisungen")],
        "Sabrina": [("av", "vertraege"), ("pf", "personalunterlagen")],
        "Bruno": [("av", "vertraege"), ("su", "unterweisungen"), ("pf", "personalunterlagen")],
        "Klara": [("av", "vertraege"), ("pf", "personalunterlagen")],
        "Inge": [("av", "vertraege"), ("su", "unterweisungen")],
        "Lukas": [("av", "vertraege")],
        "Greta": [("pf", "personalunterlagen")],
    }

    total_docs = 0
    for wkey, docs in doc_plan.items():
        worker = workers.get(wkey)
        if not worker:
            continue
        customer, role, dob, address, iban = worker_meta[wkey]

        for dtype, cat_slug in docs:
            doc_id = str(uuid.uuid4())
            fn = f"{dtype}_{wkey.lower()}_{doc_id[:8]}.pdf"

            if dtype == "av":
                pdf = gen_arbeitsvertrag(
                    worker.full_name, "01.10.2025", "16.50", role, customer, doc_id
                )
                doc_name = f"Arbeitsvertrag {worker.full_name}"
            elif dtype == "gs":
                pdf = gen_gabelstapler(worker.full_name, "15.09.2023", "31.03.2026", doc_id)
                doc_name = "Befähigungsnachweis Gabelstapler"
            elif dtype == "su":
                pdf = gen_unterweisung(worker.full_name, "01.10.2025", customer, doc_id)
                doc_name = f"Sicherheitsunterweisung {customer}"
            elif dtype == "pf":
                pdf = gen_personalfragebogen(worker.full_name, dob, address, iban, doc_id)
                doc_name = f"Personalfragebogen {worker.full_name}"
            else:
                continue

            url, size = _save_pdf(fn, pdf)
            db.add(
                Document(
                    id=uuid.UUID(doc_id),
                    tenant_id=tenant_id,
                    created_by=admin.id,
                    name=doc_name,
                    original_filename=fn,
                    file_url=url,
                    mime_type="application/pdf",
                    file_size=size,
                    checksum=_checksum(pdf),
                    category_id=cat_map.get(cat_slug),
                    linked_entity_type="worker",
                    linked_entity_id=worker.id,
                    processing_status="done",
                    status="active",
                    is_latest_version=True,
                    version_number=1,
                )
            )
            total_docs += 1

    await db.flush()
    print(f"   ✓ {total_docs} Dokumente")


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="QuickWork Demo-Seed")
    parser.add_argument(
        "--reset", action="store_true", help="Bestehende QuickWork-Daten löschen und neu anlegen"
    )
    args = parser.parse_args()
    print("🚀 QuickWork Demo-Seed startet …")
    asyncio.run(seed(reset=args.reset))
