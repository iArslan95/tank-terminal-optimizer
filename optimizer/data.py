"""Synthetic scenario generation for a liquid-bulk tank terminal.

Everything here is fake but realistic: vessel sizes, pump rates, tank
capacities and product families are in the right order of magnitude for a
Rotterdam-style terminal. No real terminal or customer data is used.
"""
from __future__ import annotations

import dataclasses
import random
from dataclasses import dataclass
from typing import Optional

MIN_PER_HOUR = 60
SETUP_MIN = 120  # mooring, hose connection, paperwork — fixed per port call


@dataclass(frozen=True)
class Product:
    name: str
    family: str  # CPP (clean petroleum products) | CHEM | BIO
    color: str   # chart color


PRODUCTS = (
    Product("Gasoline 95", "CPP", "#f59e0b"),
    Product("Diesel EN590", "CPP", "#fb7185"),
    Product("Jet A-1", "CPP", "#a78bfa"),
    Product("Naphtha", "CPP", "#facc15"),
    Product("Methanol", "CHEM", "#34d399"),
    Product("MEG", "CHEM", "#2dd4bf"),
    Product("Ethanol", "BIO", "#22d3ee"),
    Product("UCOME biodiesel", "BIO", "#4ade80"),
)

# Tank lining determines which product families a tank may legally hold.
LININGS = {
    "Mild steel": frozenset({"CPP"}),
    "Epoxy coated": frozenset({"CPP", "BIO"}),
    "Stainless steel": frozenset({"CPP", "CHEM", "BIO"}),
}

SIZE_ORDER = {"S": 0, "M": 1, "L": 2}
DEMURRAGE_PER_DAY = {"S": 9_000.0, "M": 18_000.0, "L": 30_000.0}  # EUR/day waiting

VESSEL_NAMES = (
    "MT Aurora", "MT Blue Heron", "MT Cygnus", "MT Delta Star",
    "MT Eemshaven", "MT Falcon", "MT Gannet", "MT Horizon",
    "MT IJssel", "MT Jade", "MT Kingfisher", "MT Lyra",
)


@dataclass(frozen=True)
class Berth:
    name: str
    max_size: str   # largest vessel class it can take (classes nest: L > M > S)
    pump_rate: int  # m3/h

    def fits(self, vessel: "Vessel") -> bool:
        return SIZE_ORDER[vessel.size] <= SIZE_ORDER[self.max_size]


BERTH_TEMPLATES = (
    Berth("Jetty 1", "L", 1_400),
    Berth("Jetty 2", "L", 1_100),
    Berth("Jetty 3", "M", 900),
    Berth("Jetty 4", "S", 700),
)


@dataclass(frozen=True)
class Tank:
    name: str
    capacity: int                       # m3
    level: int                          # m3 currently stored
    product: Optional[Product]          # None = empty
    last_product: Optional[Product]     # residue, relevant for cleaning when empty
    lining: str
    clean_hours: int
    clean_cost: float                   # EUR

    @property
    def free(self) -> int:
        return self.capacity - self.level

    def allows(self, product: Product) -> bool:
        return product.family in LININGS[self.lining]


@dataclass(frozen=True)
class Vessel:
    name: str
    size: str             # S / M / L
    operation: str        # IMPORT (discharge into tank) / EXPORT (load from tank)
    product: Product
    volume: int           # m3
    eta_min: int          # minutes after plan start
    demurrage_day: float  # EUR per day of waiting


@dataclass(frozen=True)
class Scenario:
    seed: int
    horizon_min: int
    vessels: tuple
    berths: tuple
    tanks: tuple


def service_minutes(vessel: Vessel, berth: Berth) -> int:
    """Berth occupation: fixed setup plus pumping time at the berth's rate."""
    return SETUP_MIN + int(round(vessel.volume / berth.pump_rate * MIN_PER_HOUR))


def tank_options(vessel: Vessel, tank: Tank):
    """Return (feasible, needs_cleaning) for serving this vessel from this tank.

    EXPORT: the tank must hold the exact product with enough stock.
    IMPORT: same product on top of existing stock is fine; an empty tank works
    too, but switching product over a different residue requires cleaning.
    """
    if vessel.operation == "EXPORT":
        ok = (
            tank.product is not None
            and tank.product.name == vessel.product.name
            and tank.level >= vessel.volume
        )
        return ok, False
    if not tank.allows(vessel.product):
        return False, False
    if tank.product is not None:
        same = tank.product.name == vessel.product.name
        return (same and tank.free >= vessel.volume), False
    if tank.capacity < vessel.volume:
        return False, False
    needs_clean = (
        tank.last_product is not None
        and tank.last_product.name != vessel.product.name
    )
    return True, needs_clean


def delay_vessel(scenario: Scenario, vessel_name: str, delay_min: int) -> Scenario:
    """What-if: push one vessel's ETA back (e.g. weather, port congestion)."""
    vessels = tuple(
        dataclasses.replace(v, eta_min=v.eta_min + delay_min) if v.name == vessel_name else v
        for v in scenario.vessels
    )
    return dataclasses.replace(scenario, vessels=vessels)


def _round_down(value: float, step: int) -> int:
    return int(value // step * step)


def _make_tanks(rng: random.Random, n_tanks: int):
    capacities = (5_000, 8_000, 12_000, 16_000, 20_000, 30_000)
    cap_weights = (0.15, 0.20, 0.20, 0.20, 0.15, 0.10)
    lining_names = list(LININGS)
    lining_weights = (0.40, 0.30, 0.30)

    tanks = []
    for i in range(n_tanks):
        lining = rng.choices(lining_names, weights=lining_weights, k=1)[0]
        capacity = rng.choices(capacities, weights=cap_weights, k=1)[0]
        allowed = [p for p in PRODUCTS if p.family in LININGS[lining]]
        product = None
        last_product = None
        level = 0
        if rng.random() < 0.45:  # tank currently in use
            product = rng.choice(allowed)
            last_product = product
            level = _round_down(rng.uniform(0.30, 0.85) * capacity, 100)
        elif rng.random() < 0.75:  # empty but with residue from previous customer
            last_product = rng.choice(allowed)
        tanks.append(
            Tank(
                name=f"TK-{101 + i}",
                capacity=capacity,
                level=level,
                product=product,
                last_product=last_product,
                lining=lining,
                clean_hours=rng.randint(6, 14),
                clean_cost=_round_down(rng.uniform(8_000, 22_000), 500),
            )
        )
    return tanks


def _size_for(volume: int) -> str:
    if volume < 8_000:
        return "S"
    if volume < 18_000:
        return "M"
    return "L"


def _try_generate(rng, n_vessels, n_berths, n_tanks, horizon_days, congestion, demurrage_scale):
    horizon_min = horizon_days * 24 * MIN_PER_HOUR
    berths = tuple(BERTH_TEMPLATES[:n_berths])
    tanks = _make_tanks(rng, n_tanks)

    # ETAs bunch into the front of the horizon as congestion rises.
    window = horizon_min * max(0.15, 1.0 - 0.85 * congestion)

    names = rng.sample(VESSEL_NAMES, k=n_vessels)
    claimed = set()
    vessels = []
    for name in names:
        want_export = rng.random() >= 0.55
        exportable = [
            t for t in tanks
            if t.name not in claimed and t.product is not None and t.level >= 3_000
        ]
        importable = [
            t for t in tanks
            if t.name not in claimed
            and ((t.product is None and t.capacity >= 3_000)
                 or (t.product is not None and t.free >= 2_500))
        ]
        if want_export and exportable:
            tank = rng.choice(exportable)
            volume = max(2_000, _round_down(rng.uniform(0.40, 0.90) * tank.level, 100))
            product, operation = tank.product, "EXPORT"
        elif importable:
            tank = rng.choice(importable)
            operation = "IMPORT"
            if tank.product is not None:
                product = tank.product
                volume = max(2_000, _round_down(rng.uniform(0.40, 0.90) * tank.free, 100))
            else:
                allowed = [p for p in PRODUCTS if tank.allows(p)]
                # Sometimes reuse the residue product (no cleaning), sometimes
                # switch product so cleaning trade-offs show up in the plan.
                if tank.last_product is not None and rng.random() < 0.5:
                    product = tank.last_product
                else:
                    product = rng.choice(allowed)
                volume = max(2_000, _round_down(rng.uniform(0.35, 0.85) * tank.capacity, 100))
        elif exportable:
            tank = rng.choice(exportable)
            volume = max(2_000, _round_down(rng.uniform(0.40, 0.90) * tank.level, 100))
            product, operation = tank.product, "EXPORT"
        else:
            return None  # not enough usable tanks — retry with a fresh roll
        claimed.add(tank.name)

        size = _size_for(volume)
        vessels.append(
            Vessel(
                name=name,
                size=size,
                operation=operation,
                product=product,
                volume=volume,
                eta_min=_round_down(rng.uniform(0, window), 15),
                demurrage_day=DEMURRAGE_PER_DAY[size] * demurrage_scale,
            )
        )

    vessels.sort(key=lambda v: v.eta_min)
    return Scenario(
        seed=0,
        horizon_min=horizon_min,
        vessels=tuple(vessels),
        berths=berths,
        tanks=tuple(tanks),
    )


def generate(seed, n_vessels, n_berths, n_tanks, horizon_days=5, congestion=0.6,
             demurrage_scale=1.0) -> Scenario:
    """Generate a feasible scenario. Each vessel is constructed around a
    distinct compatible tank, so a feasible vessel-to-tank matching always
    exists; the optimizer is free to pick a different (cheaper) one."""
    n_vessels = min(n_vessels, n_tanks, len(VESSEL_NAMES))
    for attempt in range(40):
        rng = random.Random(seed * 1_000 + attempt)
        scenario = _try_generate(
            rng, n_vessels, n_berths, n_tanks, horizon_days, congestion, demurrage_scale
        )
        if scenario is not None:
            return dataclasses.replace(scenario, seed=seed)
    raise ValueError("Could not generate a feasible scenario; try other settings.")
