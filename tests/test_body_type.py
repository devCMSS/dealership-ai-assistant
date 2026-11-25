import pytest

from app.body_type import classify, detect_requested


@pytest.mark.parametrize("make,model,trim,expected", [
    ("Honda", "Civic", "EX", "sedan"),
    ("Honda", "Civic Hatchback", "Sport", "hatchback"),  # longer phrase wins
    ("Ford", "F-150", "XLT", "pickup"),
    ("Toyota", "RAV4", "XLE Hybrid", "suv"),
    ("Honda", "Odyssey", "", "minivan"),
    ("Ford", "Mustang", "GT", "coupe"),
    ("Acme", "Roadster", "", None),
])
def test_classify(make, model, trim, expected):
    assert classify(make, model, trim) == expected


@pytest.mark.parametrize("text,expected", [
    ("I want a sedan, nothing fancy", "sedan"),
    ("any trucks under 40k?", "pickup"),
    ("Looking for SUVs", "suv"),
    ("a crossover for the family", "suv"),
    ("hatchback please", "hatchback"),
    ("vanilla ice cream", None),  # 'van' must match as a whole word
    ("hello there", None),
])
def test_detect_requested(text, expected):
    assert detect_requested(text) == expected
