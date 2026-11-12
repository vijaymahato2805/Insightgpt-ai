from io import BytesIO
from uuid import UUID

import openpyxl
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.api.saved_dashboards as saved_dashboard_api
from app.core.security import hash_password
from app.main import app
from app.models.erp import DashboardVersion, UserDatabaseAccess
from app.models.user import User, UserRole
from tests.test_text_to_sql import _seed_nav_schema


def _definition(database_id: str, *, title="Sales overview", question="Sales by category"):
    return {
        "database_id": database_id,
        "company_mapping_id": None,
        "title": title,
        "description": "Authorized sales data with headline KPIs and detail.",
        "question": question,
        "filters": [{"filter_id": "category", "label": "Category", "field": "Category"}],
        "widgets": [
            {
                "widget_id": "sales-kpi",
                "title": "Total quantity",
                "visualization": "kpi",
                "question": "What is total quantity?",
                "layout_span": 1,
                "sql": "SELECT SUM(l.[Quantity]) AS TotalQuantity FROM dbo.[Contoso$Sales Line] l",
                "explanation": "Sums posted sales line quantities.",
                "category_field": None,
                "value_field": "TotalQuantity",
                "series_field": None,
                "drilldown_field": None,
            },
            {
                "widget_id": "sales-chart",
                "title": "Quantity by category",
                "visualization": "bar",
                "question": "Show quantity by item number.",
                "layout_span": 2,
                "sql": "SELECT l.[No_] AS Category, l.[Quantity] AS Quantity FROM dbo.[Contoso$Sales Line] l",
                "explanation": "Groups returned sales line quantities.",
                "category_field": "Category",
                "value_field": "Quantity",
                "series_field": None,
                "drilldown_field": "Category",
            },
            {
                "widget_id": "sales-detail",
                "title": "Sales detail",
                "visualization": "table",
                "question": "Show sales line detail.",
                "layout_span": 4,
                "sql": "SELECT l.[No_] AS Category, l.[Quantity] AS Quantity, l.[Document No_] AS DocumentNo FROM dbo.[Contoso$Sales Line] l",
                "explanation": "Detail rows from sales lines.",
                "category_field": "Category",
                "value_field": "Quantity",
                "series_field": None,
                "drilldown_field": "Category",
            },
        ],
    }


def _mock_query_execution(monkeypatch):
    def execute(context, validation, settings):
        sql = validation.sql
        if "SUM(" in sql:
            return ["TotalQuantity"], [{"TotalQuantity": "130.5"}], False
        rows = [
            {"Category": "A", "Quantity": "100", "DocumentNo": "=HYPERLINK(\"https://bad.invalid\")"},
            {"Category": "B", "Quantity": "20", "DocumentNo": "SO-2"},
            {"Category": "A", "Quantity": "10", "DocumentNo": "SO-3"},
        ]
        if "Document No_" in sql:
            return ["Category", "Quantity", "DocumentNo"], rows, False
        return ["Category", "Quantity"], [{"Category": row["Category"], "Quantity": row["Quantity"]} for row in rows], False

    monkeypatch.setattr(saved_dashboard_api, "execute_validated_sql", execute)


def test_saved_dashboard_persistence_versions_favorites_restore_and_fresh_render(
    client, test_session_factory, monkeypatch
):
    connection = _seed_nav_schema(client, test_session_factory)
    _mock_query_execution(monkeypatch)
    created = client.post(
        "/api/saved-dashboards", json={"dashboard": _definition(connection["id"])}
    )
    assert created.status_code == 201, created.text
    saved = created.json()
    assert saved["current_version"] == 1
    assert saved["is_favorite"] is False

    with test_session_factory() as db:
        version = db.scalar(select(DashboardVersion).where(DashboardVersion.dashboard_id == UUID(saved["id"])))
        assert version is not None
        assert "rows" not in version.snapshot
        assert version.snapshot["plan"]["widgets"][0]["visualization"] == "kpi"

    rendered = client.get(f"/api/saved-dashboards/{saved['id']}")
    assert rendered.status_code == 200, rendered.text
    assert rendered.json()["widgets"][0]["rows"] == [{"TotalQuantity": "130.5"}]
    assert rendered.json()["filters"][0]["options"] == ["A", "B"]
    filtered = client.get(
        f"/api/saved-dashboards/{saved['id']}",
        params={"filters": '{"category":"A"}'},
    )
    assert filtered.status_code == 200, filtered.text
    assert len(filtered.json()["widgets"][1]["rows"]) == 2
    assert len(filtered.json()["widgets"][2]["rows"]) == 2
    assert filtered.json()["widgets"][0]["rows"] == [{"TotalQuantity": "130.5"}]
    invalid_filter = client.get(
        f"/api/saved-dashboards/{saved['id']}",
        params={"filters": '{"category":"not-an-option"}'},
    )
    assert invalid_filter.status_code == 422

    favorite = client.patch(
        f"/api/saved-dashboards/{saved['id']}/favorite", json={"is_favorite": True}
    )
    assert favorite.status_code == 200
    assert favorite.json()["is_favorite"] is True
    listing = client.get("/api/saved-dashboards")
    assert listing.status_code == 200
    assert listing.json()["items"][0]["id"] == saved["id"]

    updated = _definition(connection["id"], title="Sales overview v2", question="Updated sales overview")
    version_two = client.put(
        f"/api/saved-dashboards/{saved['id']}",
        json={"expected_version": 1, "dashboard": updated},
    )
    assert version_two.status_code == 200, version_two.text
    assert version_two.json()["current_version"] == 2
    assert version_two.json()["title"] == "Sales overview v2"
    stale_update = client.put(
        f"/api/saved-dashboards/{saved['id']}",
        json={"expected_version": 1, "dashboard": updated},
    )
    assert stale_update.status_code == 409
    history = client.get(f"/api/saved-dashboards/{saved['id']}/versions")
    assert history.status_code == 200
    assert [item["version_number"] for item in history.json()["items"]] == [2, 1]
    historical = client.get(f"/api/saved-dashboards/{saved['id']}?version_number=1")
    assert historical.status_code == 200
    assert historical.json()["title"] == "Sales overview"

    restored = client.post(f"/api/saved-dashboards/{saved['id']}/versions/1/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["current_version"] == 3
    assert restored.json()["title"] == "Sales overview"


def test_saved_dashboard_exports_excel_with_real_filtered_rows_kpis_and_chart_and_pdf(
    client, test_session_factory, monkeypatch
):
    connection = _seed_nav_schema(client, test_session_factory)
    _mock_query_execution(monkeypatch)
    created = client.post(
        "/api/saved-dashboards", json={"dashboard": _definition(connection["id"])}
    )
    assert created.status_code == 201, created.text
    dashboard_id = created.json()["id"]

    excel = client.get(
        f"/api/saved-dashboards/{dashboard_id}/export",
        params={"format": "xlsx", "filters": '{"category":"A"}'},
    )
    assert excel.status_code == 200, excel.text
    assert "spreadsheetml.sheet" in excel.headers["content-type"]
    workbook = openpyxl.load_workbook(BytesIO(excel.content), data_only=False)
    assert {"Overview", "Total quantity", "Quantity by category", "Sales detail"}.issubset(workbook.sheetnames)
    overview = workbook["Overview"]
    assert any(cell.value == "A" for row in overview.iter_rows() for cell in row)
    assert overview.cell(11, 3).value == 130.5
    chart_sheet = workbook["Quantity by category"]
    assert len(chart_sheet._charts) == 1
    assert [chart_sheet.cell(row, 1).value for row in (7, 8)] == ["A", "A"]
    detail_sheet = workbook["Sales detail"]
    assert detail_sheet.cell(7, 1).value == "A"
    assert detail_sheet.cell(7, 3).data_type != "f"
    assert detail_sheet.cell(7, 3).value.startswith("'=")

    pdf = client.get(
        f"/api/saved-dashboards/{dashboard_id}/export",
        params={"format": "pdf", "filters": '{"category":"A"}'},
    )
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-")
    assert pdf.content.rstrip().endswith(b"%%EOF")


def test_saved_dashboard_rejects_unsafe_sql_and_requires_database_grant(
    client, test_session_factory
):
    connection = _seed_nav_schema(client, test_session_factory)
    unsafe = _definition(connection["id"])
    unsafe["widgets"][0]["sql"] = "DELETE FROM dbo.[Contoso$Sales Line]"
    denied_sql = client.post("/api/saved-dashboards", json={"dashboard": unsafe})
    assert denied_sql.status_code == 422

    with test_session_factory() as db:
        admin = db.scalar(select(User).where(User.email == "admin@example.com"))
        viewer = User(
            email="saved-viewer@example.com",
            full_name="Saved Viewer",
            password_hash=hash_password("saved dashboard viewer password"),
            role=UserRole.VIEWER.value,
        )
        db.add(viewer)
        db.flush()
        db.add(UserDatabaseAccess(
            user_id=viewer.id,
            database_connection_id=UUID(connection["id"]),
            permission="read",
            granted_by=admin.id,
        ))
        db.commit()

    with TestClient(app) as viewer_client:
        login = viewer_client.post(
            "/api/auth/login",
            json={"email": "saved-viewer@example.com", "password": "saved dashboard viewer password"},
        )
        assert login.status_code == 200
        viewer_saved = viewer_client.post(
            "/api/saved-dashboards", json={"dashboard": _definition(connection["id"])}
        )
        assert viewer_saved.status_code == 201, viewer_saved.text
        with test_session_factory() as db:
            db.query(UserDatabaseAccess).filter_by(
                user_id=viewer.id, database_connection_id=UUID(connection["id"])
            ).delete()
            db.commit()
        denied_export = viewer_client.get(
            f"/api/saved-dashboards/{viewer_saved.json()['id']}/export?format=pdf"
        )
    assert denied_export.status_code == 404
