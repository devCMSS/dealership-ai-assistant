from app.db import Database
from app.models import LeadUpdate, VehicleFilters
from app.repository import LeadRepository, VehicleRepository
from app.seed import DEMO_VEHICLES, seed_if_empty


def make_repo(tmp_path):
    db = Database(tmp_path / "r.db")
    db.init()
    repo = VehicleRepository(db)
    seed_if_empty(repo)
    return db, repo


def test_seed_runs_once(tmp_path):
    _, repo = make_repo(tmp_path)
    assert repo.count() == len(DEMO_VEHICLES)
    assert seed_if_empty(repo) == 0


def test_filters_combine(tmp_path):
    _, repo = make_repo(tmp_path)
    suvs = repo.search(VehicleFilters(body_type="suv", max_price=35000))
    assert suvs and all(v.body_type == "suv" and v.price <= 35000 for v in suvs)
    cheapest_first = repo.search(VehicleFilters(sort="price_asc"))
    assert [v.price for v in cheapest_first] == sorted(v.price for v in cheapest_first)


def test_search_text_is_parameterized(tmp_path):
    _, repo = make_repo(tmp_path)
    assert repo.search(VehicleFilters(q="' OR 1=1 --")) == []
    assert repo.count() == len(DEMO_VEHICLES)


def test_hidden_vehicles_are_not_public(tmp_path):
    _, repo = make_repo(tmp_path)
    repo.set_active(1, False)
    assert repo.get(1) is None
    assert repo.get(1, include_inactive=True) is not None
    assert all(v.id != 1 for v in repo.search(VehicleFilters()))


def test_lead_needs_name_or_contact_and_merges(tmp_path):
    db, _ = make_repo(tmp_path)
    leads = LeadRepository(db)
    assert leads.upsert("s1", LeadUpdate(interest="test drive")) is False
    assert leads.list() == []
    assert leads.upsert("s1", LeadUpdate(customer_name="Ana")) is True
    assert leads.upsert("s1", LeadUpdate(contact="ana@example.com", interest="RAV4")) is True
    (lead,) = leads.list()
    assert (lead["name"], lead["contact"], lead["interest"]) == ("Ana", "ana@example.com", "RAV4")
