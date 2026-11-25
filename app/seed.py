"""Fictional demo inventory. Prices and mileages are made up for the demo."""

from __future__ import annotations

from .models import VehicleIn
from .repository import VehicleRepository

DEMO_VEHICLES: list[dict] = [
    dict(make="Toyota", model="Camry", trim="SE", year=2022, body_type="sedan", condition="used",
         price=24900, mileage=31200, transmission="automatic", fuel="gasoline", color="Celestial Silver",
         description="One owner, clean history, adaptive cruise and Apple CarPlay.", featured=True),
    dict(make="Honda", model="Civic", trim="EX", year=2021, body_type="sedan", condition="certified",
         price=21800, mileage=28400, transmission="cvt", fuel="gasoline", color="Aegean Blue",
         description="Certified pre-owned with extended powertrain warranty."),
    dict(make="Hyundai", model="Elantra", trim="SEL", year=2023, body_type="sedan", condition="used",
         price=19500, mileage=18900, transmission="automatic", fuel="gasoline", color="Intense Blue",
         description="Great commuter: 37 mpg highway and blind-spot monitoring."),
    dict(make="Tesla", model="Model 3", trim="Long Range", year=2022, body_type="sedan", condition="used",
         price=29900, mileage=35600, transmission="automatic", fuel="electric", color="Pearl White",
         description="Dual motor AWD, about 330 miles of range, glass roof.", featured=True),
    dict(make="Toyota", model="RAV4", trim="XLE Hybrid", year=2023, body_type="suv", condition="used",
         price=33400, mileage=15800, transmission="cvt", fuel="hybrid", color="Blueprint",
         description="AWD hybrid, 40 mpg combined, power liftgate.", featured=True),
    dict(make="Honda", model="CR-V", trim="EX-L", year=2022, body_type="suv", condition="certified",
         price=30900, mileage=24100, transmission="cvt", fuel="gasoline", color="Platinum White",
         description="Leather, heated seats, Honda Sensing suite."),
    dict(make="Ford", model="Explorer", trim="XLT", year=2021, body_type="suv", condition="used",
         price=28700, mileage=41300, transmission="automatic", fuel="gasoline", color="Carbonized Gray",
         description="Three rows, seats seven, towing package."),
    dict(make="Kia", model="Telluride", trim="EX", year=2024, body_type="suv", condition="new",
         price=42900, mileage=0, transmission="automatic", fuel="gasoline", color="Everlasting Silver",
         description="Brand new, 8 seats, captain chairs available."),
    dict(make="Ford", model="F-150", trim="XLT SuperCrew", year=2022, body_type="pickup", condition="used",
         price=38900, mileage=29800, transmission="automatic", fuel="gasoline", color="Antimatter Blue",
         description="2.7L EcoBoost, 4x4, Pro Power Onboard.", featured=True),
    dict(make="Toyota", model="Tacoma", trim="TRD Off-Road", year=2021, body_type="pickup", condition="used",
         price=34500, mileage=38700, transmission="automatic", fuel="gasoline", color="Army Green",
         description="Crawl control, locking rear differential, bed liner."),
    dict(make="Volkswagen", model="Golf", trim="GTI S", year=2022, body_type="hatchback", condition="used",
         price=26900, mileage=22500, transmission="manual", fuel="gasoline", color="Kings Red",
         description="Six-speed manual, plaid seats, the fun daily driver."),
    dict(make="Toyota", model="Prius", trim="LE", year=2023, body_type="hatchback", condition="used",
         price=27500, mileage=12600, transmission="cvt", fuel="hybrid", color="Wind Chill Pearl",
         description="New-generation Prius, 57 mpg combined."),
    dict(make="Ford", model="Mustang", trim="GT", year=2020, body_type="coupe", condition="used",
         price=31900, mileage=33900, transmission="manual", fuel="gasoline", color="Race Red",
         description="5.0L V8, performance package, active exhaust."),
    dict(make="Honda", model="Odyssey", trim="EX-L", year=2022, body_type="minivan", condition="used",
         price=32400, mileage=27700, transmission="automatic", fuel="gasoline", color="Modern Steel",
         description="Magic Slide seats, rear entertainment, seats eight."),
]


def seed_if_empty(repo: VehicleRepository) -> int:
    if repo.count():
        return 0
    for data in DEMO_VEHICLES:
        repo.create(VehicleIn.model_validate(data))
    return len(DEMO_VEHICLES)
