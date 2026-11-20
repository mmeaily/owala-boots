"""
Parametric bottle boot generator
================================

Units: millimetres

A printed TPU boot for the bottom of a water bottle, with a hidden
pocket for an Apple AirTag:

    boot    cup the bottle's base pushes down into; the inside is a
            little smaller than the bottle (FIT_SQUEEZE) so the TPU
            stretches over it and grips
    pocket  in the floor, under a small lip; the AirTag is pressed in
            from inside the boot, and with the bottle in, the
            bottle's bottom covers it

A push hole under the AirTag lets it be pushed back out from below,
a ring of small holes lets its speaker be heard, and drain holes near
the wall let water out after washing.

Requires:
    CadQuery, matplotlib (preview only)

Bottle profiles:
    params.json                    boot and AirTag settings, shared
    bottles/<name>/bottle.json     one bottle's measurements ("bottle"
                                   group); may also override any key
                                   from params.json

Run:
    python generate.py                      every profile in bottles/
    python generate.py bottles/<name>       one profile

Output (in the profile's folder):
    <name>_boot.stl     boot, in print orientation
    <name>_preview.png  fitted / exploded / section / part views

Printing: TPU 90A, floor on the bed, open side up, no supports.  The
only overhang is the lip over the AirTag pocket (LIP, under 1 mm).

Fitting:
    1. Press the AirTag into the pocket, white side up, past the lip.
    2. Push the bottle down into the boot.
"""

import json
import math
import subprocess
import sys
from pathlib import Path

import cadquery as cq


# ============================================================
# PARAMETERS
# ============================================================

HERE = Path(__file__).parent
PARAMS_FILE = HERE / "params.json"
BOTTLES_DIR = HERE / "bottles"
PROFILE_NAME = "bottle.json"


def profile_dirs():

    return sorted(path.parent for path in BOTTLES_DIR.glob(f"*/{PROFILE_NAME}"))


# No profile given: build each one in its own run (the build below
# runs once, at import, for one profile).
if len(sys.argv) < 2:
    if __name__ != "__main__":
        sys.exit("Name a bottle profile: bottles/<name>")
    profiles = profile_dirs()
    if not profiles:
        sys.exit(f"No profiles: add {BOTTLES_DIR / '<name>' / PROFILE_NAME}")
    failed = []
    for profile in profiles:
        print(f"\n##### {profile.name}")
        if subprocess.run([sys.executable, __file__, str(profile)]).returncode:
            failed.append(profile.name)
    print()
    print(f"Built {len(profiles) - len(failed)} of {len(profiles)} profiles"
          + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    sys.exit(1 if failed else 0)

# fit_test.py imports this file with the same argument.
PROFILE_DIR = Path(sys.argv[1])
if PROFILE_DIR.name == PROFILE_NAME:
    PROFILE_DIR = PROFILE_DIR.parent
PROFILE_FILE = PROFILE_DIR / PROFILE_NAME


def load_params(path):
    """
    Read a grouped parameter file into a flat {name: value} dict.
    Groups and keys starting with '_' are notes and are skipped.
    """

    try:
        with open(path, encoding="utf-8") as file:
            groups = json.load(file)
    except FileNotFoundError:
        sys.exit(f"Parameter file not found: {path}")
    except json.JSONDecodeError as error:
        sys.exit(f"{path}: invalid JSON - {error}")

    flat = {}

    for group, values in groups.items():
        if group.startswith("_"):
            continue
        for name, value in values.items():
            if name.startswith("_"):
                continue
            if name in flat:
                sys.exit(f"{path}: '{name}' appears more than once")
            flat[name] = value

    return flat


# The profile's keys win over the shared ones.
_params = {**load_params(PARAMS_FILE), **load_params(PROFILE_FILE)}


def param(name):
    try:
        return _params.pop(name)
    except KeyError:
        sys.exit(f"{PROFILE_FILE}: missing parameter '{name}'")


# Bottle
BASE_DIAMETER = param("BASE_DIAMETER")
UPPER_DIAMETER = param("UPPER_DIAMETER")
UPPER_HEIGHT = param("UPPER_HEIGHT")
CORNER_RADIUS = param("CORNER_RADIUS")

# Boot
WALL = param("WALL")
WALL_HEIGHT = param("WALL_HEIGHT")
FIT_SQUEEZE = param("FIT_SQUEEZE")
FLOOR_UNDER = param("FLOOR_UNDER")
BOTTOM_ROUND = param("BOTTOM_ROUND")
TOP_ROUND = param("TOP_ROUND")
DRAIN_HOLES = param("DRAIN_HOLES")
DRAIN_DIAMETER = param("DRAIN_DIAMETER")

# AirTag
AIRTAG_DIAMETER = param("AIRTAG_DIAMETER")
AIRTAG_THICKNESS = param("AIRTAG_THICKNESS")
AIRTAG_CLEARANCE = param("AIRTAG_CLEARANCE")
AIRTAG_HEADROOM = param("AIRTAG_HEADROOM")
LIP = param("LIP")
LIP_HEIGHT = param("LIP_HEIGHT")
PUSH_HOLE_DIAMETER = param("PUSH_HOLE_DIAMETER")
SOUND_HOLES = param("SOUND_HOLES")
SOUND_HOLE_DIAMETER = param("SOUND_HOLE_DIAMETER")
SPRING_BUMPS = param("SPRING_BUMPS")
SPRING_HEIGHT = param("SPRING_HEIGHT")
SPRING_DIAMETER = param("SPRING_DIAMETER")

# Texture
TEXTURE = param("TEXTURE")
TEXTURE_RELIEF = param("TEXTURE_RELIEF")
TEXTURE_PANEL = param("TEXTURE_PANEL")

# Output
PREVIEW = param("PREVIEW")
CHECK_FIT = param("CHECK_FIT")
TPU_DENSITY = param("TPU_DENSITY")

OUTPUT_PREFIX = PROFILE_DIR.resolve().name
PREVIEW_FILE = f"{OUTPUT_PREFIX}_preview.png"

# STL mesh: fine enough that the round wall prints round.  At the old
# 0.1 rad the wall was a 64-sided polygon, and the short facet where the
# revolve closes printed as a vertical scar (first print, 2026-11-06).
STL_TOLERANCE = 0.005
STL_ANGULAR_TOLERANCE = 0.02


# A typo in a key would otherwise be silently ignored.
if _params:
    sys.exit(
        f"{PROFILE_FILE}: unknown parameter(s): "
        + ", ".join(sorted(_params))
    )

print(f"Profile: {PROFILE_FILE}")


# ============================================================
# DERIVED DIMENSIONS
# ============================================================

# Coordinates (as printed and as fitted, bottle upright):
#
#   Z  up the bottle's axis; z = 0 is the bottom of the boot
#   R  out from the axis
#
#   half section:
#
#        │    bottle    │█ wall
#        │              │█
#        │              │█
#         ╲____________╱ █  bottle bottom on the floor top
#   ██████  ▄▄▄▄▄▄▄▄  ███  lip over the pocket
#   ██████  AirTag    ██████
#   ███   ▀▀  ▀▀  ▀▀  ███   floor under the AirTag, push / sound holes
#
# The boot is a revolved half section; the holes are cut afterwards.

c = FIT_SQUEEZE / 2.0
has_lip = LIP > 0.0

# Bottle: its side is a straight line through BASE_DIAMETER (taken at
# CORNER_RADIUS above the table) and UPPER_DIAMETER at UPPER_HEIGHT.
base_radius = BASE_DIAMETER / 2.0
taper = (UPPER_DIAMETER - BASE_DIAMETER) / 2.0 / (UPPER_HEIGHT - CORNER_RADIUS)


def bottle_radius(height):
    """Radius of the bottle's side, height above its bottom."""

    return base_radius + taper * (height - CORNER_RADIUS)


bottle_flat = base_radius - CORNER_RADIUS     # edge of the flat bottom

# AirTag pocket.
pocket_radius = (AIRTAG_DIAMETER + AIRTAG_CLEARANCE) / 2.0
pocket_top = FLOOR_UNDER + AIRTAG_THICKNESS + AIRTAG_HEADROOM   # under the lip
lip_radius = pocket_radius - LIP
floor_top = pocket_top + (LIP_HEIGHT if has_lip else 0.0)
push_radius = PUSH_HOLE_DIAMETER / 2.0
sound_radius = SOUND_HOLE_DIAMETER / 2.0
sound_ring = (push_radius + pocket_radius) / 2.0
spring_radius = SPRING_DIAMETER / 2.0
spring_ring = (push_radius + sound_ring - sound_radius) / 2.0   # between the push and sound holes

# Boot.
top_z = floor_top + WALL_HEIGHT


def inner_radius(z):
    """Inside of the wall at height z."""

    return bottle_radius(z - floor_top) - c


def outer_radius(z):

    return inner_radius(z) + WALL


inner_flat = bottle_flat - c                  # where the inside corner meets the floor
drain_radius = DRAIN_DIAMETER / 2.0
drain_ring = inner_flat - drain_radius - 0.5

# Texture band on the outside of the wall, clear of the rounded edges.
TEXTURES = ("none", "cabana", "surf")
band_low = BOTTOM_ROUND + 1.0
band_high = top_z - TOP_ROUND - 1.5
band_height = band_high - band_low
band_middle = (band_low + band_high) / 2.0
# Panels round the wall, a multiple of 3 (three motifs take turns).
panels = 3 * max(1, round(2.0 * math.pi * outer_radius(band_middle) / TEXTURE_PANEL / 3.0))
panel_width = 2.0 * math.pi * outer_radius(band_middle) / panels
motif_size = min(0.6 * band_height, 0.62 * panel_width)


# ============================================================
# SANITY CHECKS
# ============================================================

problems = []

if UPPER_HEIGHT <= CORNER_RADIUS:
    problems.append("UPPER_HEIGHT must be above the rounded bottom edge (CORNER_RADIUS)")

if WALL_HEIGHT < CORNER_RADIUS + 5.0:
    problems.append("WALL_HEIGHT must reach at least 5 mm above the rounded bottom edge (CORNER_RADIUS)")

if pocket_radius + 1.5 > inner_flat:
    problems.append("The AirTag pocket is wider than the bottle's flat bottom (BASE_DIAMETER, CORNER_RADIUS)")

if TOP_ROUND >= WALL / 2.0:
    problems.append("TOP_ROUND must be less than half the WALL")

if BOTTOM_ROUND >= floor_top or BOTTOM_ROUND >= outer_radius(0.0) - drain_ring - drain_radius:
    problems.append("BOTTOM_ROUND is too big for the floor")

if has_lip and LIP > LIP_HEIGHT * 1.5:
    problems.append("LIP overhangs more than 1.5 x LIP_HEIGHT; it will not print without support")

if push_radius > AIRTAG_DIAMETER / 2.0 - 4.0:
    problems.append("PUSH_HOLE_DIAMETER is too big; the AirTag needs at least 4 mm of floor round it")

if SOUND_HOLES and (sound_ring - sound_radius < push_radius + 0.8
                    or sound_ring + sound_radius > pocket_radius - 0.8):
    problems.append("The sound holes do not fit between the push hole and the pocket's edge")

if SPRING_BUMPS and (spring_ring - spring_radius < push_radius + 0.4
                     or spring_ring + spring_radius > sound_ring - sound_radius - 0.4):
    problems.append("The spring bumps do not fit between the push hole and the sound holes (SPRING_DIAMETER)")

if SPRING_BUMPS and SPRING_HEIGHT <= AIRTAG_HEADROOM:
    problems.append("SPRING_HEIGHT must be more than AIRTAG_HEADROOM, or the bumps never touch the AirTag")

if DRAIN_HOLES and drain_ring - drain_radius < pocket_radius + 1.0:
    problems.append("The drain holes do not fit between the AirTag pocket and the wall")

if TEXTURE not in TEXTURES:
    problems.append(f"TEXTURE must be one of: {', '.join(TEXTURES)}")
elif TEXTURE != "none":
    if TEXTURE_RELIEF <= 0.0 or TEXTURE_RELIEF > WALL:
        problems.append("TEXTURE_RELIEF must be more than 0 and no more than the WALL")
    if band_height < 15.0:
        problems.append("The wall is too short for a texture (WALL_HEIGHT)")

if problems:
    print()
    for problem in problems:
        print(f"ERROR: {problem}")
    sys.exit(1)


# ============================================================
# HELPERS
# ============================================================

def revolve(points):
    """
    Solid from a closed half section turned round the Z axis.
    points: (r, z) corners; ("arc", (r, z) middle, (r, z) end) for an arc.
    """

    wp = cq.Workplane("XZ").moveTo(*points[0])
    for point in points[1:]:
        if point[0] == "arc":
            wp = wp.threePointArc(point[1], point[2])
        else:
            wp = wp.lineTo(*point)

    return wp.close().revolve(360.0, (0, 0, 0), (0, 1, 0))


def arc_middle(centre, radius, angle0, angle1):
    """Point halfway round an arc (angles in degrees, from +R)."""

    angle = math.radians((angle0 + angle1) / 2.0)
    return (centre[0] + radius * math.cos(angle), centre[1] + radius * math.sin(angle))


def outline(points, steps=12):
    """The half section as plain (r, z) points, arcs sampled, for drawing."""

    out = [points[0]]
    for point in points[1:]:
        if point[0] != "arc":
            out.append(point)
            continue
        (x1, y1), (x2, y2), (x3, y3) = out[-1], point[1], point[2]
        # Circle through the three points.
        d = 2.0 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
        ux = ((x1**2 + y1**2) * (y2 - y3) + (x2**2 + y2**2) * (y3 - y1) + (x3**2 + y3**2) * (y1 - y2)) / d
        uy = ((x1**2 + y1**2) * (x3 - x2) + (x2**2 + y2**2) * (x1 - x3) + (x3**2 + y3**2) * (x2 - x1)) / d
        radius = math.hypot(x1 - ux, y1 - uy)
        a1 = math.atan2(y1 - uy, x1 - ux)
        a2 = math.atan2(y2 - uy, x2 - ux)
        a3 = math.atan2(y3 - uy, x3 - ux)
        # Go round the way that passes the middle point.
        sweep = (a3 - a1) % (2.0 * math.pi)
        if (a2 - a1) % (2.0 * math.pi) > sweep:
            sweep -= 2.0 * math.pi
        for i in range(1, steps + 1):
            a = a1 + sweep * i / steps
            out.append((ux + radius * math.cos(a), uy + radius * math.sin(a)))

    return out + [out[0]]


def cylinder_z(radius, z0, z1, x=0.0, y=0.0):

    return (
        cq.Workplane("XY")
        .circle(radius)
        .extrude(z1 - z0)
        .translate((x, y, z0))
    )


def hole_ring(count, ring, radius, z0, z1):
    """count upright holes evenly round a circle of radius ring."""

    return (
        cq.Workplane("XY")
        .polarArray(ring, 0.0, 360.0, count)
        .circle(radius)
        .extrude(z1 - z0)
        .translate((0, 0, z0))
    )


def box(x0, x1, y0, y1, z0, z1):

    return (
        cq.Workplane("XY")
        .box(x1 - x0, y1 - y0, z1 - z0, centered=False)
        .translate((x0, y0, z0))
    )


def rounded(shape, selector, radius, what):
    """Fillet the selected edges, or leave them sharp if OCC refuses."""

    try:
        return shape.edges(selector).fillet(radius)
    except Exception as error:
        print(f"WARNING: {what} fillet skipped: {error}")
        return shape


def to_bed(shape):
    """Move a shape so its lowest point is on z = 0."""

    bb = shape.val().BoundingBox()
    return shape.translate((0, 0, -bb.zmin))


def volume(shape):

    return sum(solid.Volume() for solid in shape.solids().vals())


# ============================================================
# BOTTLE AND AIRTAG (as measured, for the checks and preview)
# ============================================================

big = 400.0


def bottle_shape(height, squeeze=0.0, z0=0.0):
    """
    The bottle's lower part, bottom at z0, made squeeze smaller on the
    radius (the boot's inside).
    """

    r = CORNER_RADIUS
    centre = (bottle_flat - squeeze, z0 + r)
    return revolve([
        (0.0, z0),
        (centre[0], z0),
        ("arc", arc_middle(centre, r, -90.0, 0.0), (centre[0] + r, centre[1])),
        (bottle_radius(height) - squeeze, z0 + height),
        (0.0, z0 + height),
    ])


def airtag_shape():
    """AirTag as fitted: domed metal side down, on the pocket's floor."""

    tag = cylinder_z(AIRTAG_DIAMETER / 2.0, FLOOR_UNDER, FLOOR_UNDER + AIRTAG_THICKNESS)
    tag = rounded(tag, "<Z", 3.0, "AirTag dome")
    return rounded(tag, ">Z", 1.0, "AirTag top")


# ============================================================
# BOOT
# ============================================================

print("Building boot ...")

outer_bottom = outer_radius(BOTTOM_ROUND)
bottom_centre = (outer_bottom - BOTTOM_ROUND, BOTTOM_ROUND)
corner_centre = (inner_flat, floor_top + CORNER_RADIUS)

section = [
    (push_radius, 0.0),
    (bottom_centre[0], 0.0),
    ("arc", arc_middle(bottom_centre, BOTTOM_ROUND, -90.0, 0.0), (outer_bottom, BOTTOM_ROUND)),
    (outer_radius(top_z), top_z),
    (inner_radius(top_z), top_z),
    (inner_radius(corner_centre[1]), corner_centre[1]),
    ("arc", arc_middle(corner_centre, CORNER_RADIUS, 0.0, -90.0), (inner_flat, floor_top)),
    (pocket_radius, floor_top),
]
if has_lip:
    # Lead-in chamfer down to the lip, then its flat underside.
    section += [(lip_radius, pocket_top), (pocket_radius, pocket_top)]
section += [
    (pocket_radius, FLOOR_UNDER),
    (push_radius, FLOOR_UNDER),
]

boot = revolve(section)
boot = rounded(boot, ">Z", TOP_ROUND, "top edge")

if SOUND_HOLES:
    boot = boot.cut(hole_ring(SOUND_HOLES, sound_ring, sound_radius, -1.0, FLOOR_UNDER + 1.0))

if DRAIN_HOLES:
    boot = boot.cut(hole_ring(DRAIN_HOLES, drain_ring, drain_radius, -1.0, floor_top + 1.0))

# The fit check tests the AirTag against the pocket without the spring
# bumps, which it squashes on purpose (and skips the pocket when it is a
# press fit, AIRTAG_CLEARANCE below 0).
pocket_boot = boot

if SPRING_BUMPS:
    bumps = hole_ring(SPRING_BUMPS, spring_ring, spring_radius, FLOOR_UNDER - 0.1, FLOOR_UNDER + SPRING_HEIGHT)
    bumps = rounded(bumps, ">Z", min(0.3, SPRING_HEIGHT * 0.75), "spring bump tops")
    boot = boot.union(bumps)


# ============================================================
# TEXTURE
# ============================================================

# Optional relief round the outside of the wall (TEXTURE).  Each motif
# is drawn flat, u across and v up from the band's middle, on a plane
# facing out of the wall; it is pushed out through the wall and the lot
# is cut to a shell that follows the wall's outside, so every motif
# stands TEXTURE_RELIEF proud however the wall curves and tapers.  The
# inside, where the bottle goes, is untouched.
#
#   cabana  goes with Owala's Coral Cabana tumbler graphics (navy coral,
#           starfish and shells over stripes): pairs of stripes between
#           panels of starfish, scallop shells and coral branches, with
#           a few bubbles
#   surf    goes with Owala's Vintage Surf Sway graphics (waves, palms,
#           surfboards): two rolling wave lines round the bottom, with
#           palm trees, surfboards and suns above, and pairs of vertical
#           ridges between the panels

# The flat motifs start deep enough to reach the shell out to the
# panel's edges, where the wall curves away from them, and stop past it.
relief_reach = panel_width / 2.0 + 3.0
relief_back = math.sqrt((outer_radius(band_low) - 1.2) ** 2 - relief_reach ** 2)
relief_front = outer_radius(band_high) + TEXTURE_RELIEF + 1.0


def flat():
    """Workplane facing out of the wall at -Y: u along X, v up Z."""

    return cq.Workplane(cq.Plane(
        origin=(0.0, -relief_back, band_middle), xDir=(1.0, 0.0, 0.0), normal=(0.0, -1.0, 0.0)
    ))


def raised(sketch):

    return sketch.extrude(relief_front - relief_back)


def placed(points, u, v, turn=0.0):
    """Points turned by turn degrees, then moved to (u, v)."""

    a = math.radians(turn)
    return [(u + x * math.cos(a) - y * math.sin(a), v + x * math.sin(a) + y * math.cos(a))
            for x, y in points]


def bar(start, end, width):
    """Straight stroke with round ends."""

    (u0, v0), (u1, v1) = start, end
    length = math.hypot(u1 - u0, v1 - v0)
    return raised(
        flat().center((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        .slot2D(length + width, width, math.degrees(math.atan2(v1 - v0, u1 - u0)))
    )


def union_all(shapes):

    result = shapes[0]
    for shape in shapes[1:]:
        result = result.union(shape)
    return result


def starfish(u, v, size, turn):

    points = []
    for i in range(150):
        t = 2.0 * math.pi * i / 150
        r = size / 2.0 * (0.36 + 0.64 * ((1.0 + math.cos(5.0 * t)) / 2.0) ** 1.5)
        points.append((r * math.sin(t), r * math.cos(t)))
    return raised(flat().polyline(placed(points, u, v, turn)).close())


def scallop(u, v, size):
    """Fan shell, hinge at the bottom, scalloped rim, grooves between the ribs."""

    radius = 0.85 * size
    spread = math.radians(42.0)
    ribs = 6
    hinge = (u, v - 0.45 * size)

    rim = []
    for i in range(121):
        phi = -spread + 2.0 * spread * i / 120
        r = radius * (0.93 + 0.07 * abs(math.cos(math.pi * ribs * (phi + spread) / (2.0 * spread))))
        rim.append((hinge[0] + r * math.sin(phi), hinge[1] + r * math.cos(phi)))
    shell = raised(flat().polyline([hinge] + rim).close())

    ears = [(-0.27, -0.06), (0.27, -0.06), (0.16, 0.12), (-0.16, 0.12)]
    shell = shell.union(raised(flat().polyline(
        [(hinge[0] + x * size, hinge[1] + y * size) for x, y in ears]).close()))

    for k in range(1, ribs):
        phi = -spread + 2.0 * spread * k / ribs
        direction = (math.sin(phi), math.cos(phi))
        start = (hinge[0] + 0.3 * radius * direction[0], hinge[1] + 0.3 * radius * direction[1])
        end = (hinge[0] + 0.86 * radius * direction[0], hinge[1] + 0.86 * radius * direction[1])
        shell = shell.cut(bar(start, end, 0.8))

    return shell


# Coral branches on a 1 x 1 square: (from, to, width), scaled by size.
CORAL = [
    ((0.00, -0.50), (0.00, -0.12), 0.15),
    ((0.00, -0.12), (-0.24, 0.10), 0.12),
    ((-0.24, 0.10), (-0.28, 0.44), 0.10),
    ((-0.24, 0.10), (-0.44, 0.22), 0.09),
    ((0.00, -0.12), (0.14, 0.16), 0.12),
    ((0.14, 0.16), (0.06, 0.48), 0.10),
    ((0.14, 0.16), (0.36, 0.30), 0.09),
    ((0.36, 0.30), (0.42, 0.46), 0.08),
    ((0.00, -0.30), (0.26, -0.12), 0.10),
    ((0.26, -0.12), (0.44, 0.02), 0.08),
]


def coral(u, v, size, mirror):

    m = -1.0 if mirror else 1.0
    return union_all([
        bar((u + m * x0 * size, v + y0 * size), (u + m * x1 * size, v + y1 * size), w * size)
        for (x0, y0), (x1, y1), w in CORAL
    ])


def bubbles(u, v, size, above):
    """A few round bubbles, above or below a motif."""

    side = 1.0 if above else -1.0
    spots = [(-0.22, 0.62, 0.075), (0.18, 0.74, 0.06), (0.0, 0.90, 0.045)]
    return union_all([
        raised(flat().center(u + x * size, v + side * y * size).circle(r * size))
        for x, y, r in spots
    ])


def edge_ridges():
    """Pair of vertical ridges up the band at a panel's left edge (the
    first panel's is at the back, so the seam falls by them)."""

    edge = -panel_width / 2.0
    return [
        bar((edge + du, -band_height / 2.0 + 0.6), (edge + du, band_height / 2.0 - 0.6), 1.0)
        for du in (-1.3, 1.3)
    ]


def cabana_panel(index):
    """One panel, centred on u = 0, plus the stripe pair at its left edge."""

    lift = 0.12 * band_height * (1.0 if index % 2 == 0 else -1.0)
    kind = index % 3
    if kind == 0:
        motif = starfish(0.0, lift, motif_size, 17.0 * index)
    elif kind == 1:
        motif = scallop(0.0, lift, motif_size)
    else:
        motif = coral(0.0, lift, motif_size, mirror=index % 2 == 1)

    return union_all([motif, bubbles(0.0, lift, motif_size, above=lift < 0.0)] + edge_ridges())


def palm(u, v, size, lean):
    """Palm tree, foot at the bottom; lean +1 bends right, -1 left."""

    trunk = []
    for i in range(6):
        t = i / 5.0
        trunk.append((u + lean * 0.22 * size * t * t, v - 0.5 * size + 0.72 * size * t))
    top = trunk[-1]
    strokes = [bar(trunk[i], trunk[i + 1], (0.11 - 0.035 * i / 4.0) * size) for i in range(5)]

    # Fronds: arcs out from the crown, drooping at the tips.
    for angle, length in [(-160.0, 0.42), (-115.0, 0.36), (-65.0, 0.36), (-20.0, 0.42), (90.0, 0.2)]:
        a = math.radians(angle + lean * 8.0)
        points = []
        for i in range(5):
            t = i / 4.0
            droop = 0.18 * size * t * t if angle != 90.0 else 0.0
            points.append((top[0] + math.cos(a) * length * size * t,
                           top[1] + math.sin(a) * length * size * t * 0.6 + 0.12 * size * t - droop))
        strokes += [bar(points[i], points[i + 1], (0.09 - 0.015 * i) * size) for i in range(4)]

    strokes.append(raised(flat().pushPoints(
        [(top[0] - 0.05 * size, top[1] - 0.06 * size), (top[0] + 0.05 * size, top[1] - 0.07 * size)]
    ).circle(0.045 * size)))
    return union_all(strokes)


def surfboard(u, v, size, turn):
    """Board with a pointed nose and a groove for the stringer."""

    length, width = size, 0.26 * size
    outline_points = []
    for i in range(80):
        t = 2.0 * math.pi * i / 80
        x = width / 2.0 * math.sin(t)
        y = length / 2.0 * math.cos(t)
        # Narrower towards the nose (the top).
        x *= 1.0 - 0.35 * max(0.0, math.cos(t))
        outline_points.append((x, y))
    board = raised(flat().polyline(placed(outline_points, u, v, turn)).close())
    stringer = placed([(0.0, -0.36 * length), (0.0, 0.36 * length)], u, v, turn)
    return board.cut(bar(stringer[0], stringer[1], 0.7))


def sun(u, v, size):

    rays = [
        bar((u + 0.3 * size * math.cos(a), v + 0.3 * size * math.sin(a)),
            (u + 0.46 * size * math.cos(a), v + 0.46 * size * math.sin(a)), 0.06 * size)
        for a in (2.0 * math.pi * k / 10 for k in range(10))
    ]
    return union_all([raised(flat().center(u, v).circle(0.22 * size))] + rays)


def waves(level, amplitude, width):
    """Rolling wave line across one panel; whole waves, so the panels join up."""

    count = 2
    half = panel_width / 2.0 + 0.5
    top, bottom = [], []
    for i in range(121):
        u = -half + 2.0 * half * i / 120
        v = level + amplitude * math.cos(2.0 * math.pi * count * u / panel_width)
        top.append((u, v + width / 2.0))
        bottom.append((u, v - width / 2.0))
    return raised(flat().polyline(top + bottom[::-1]).close())


def surf_panel(index):
    """Two wave lines along the bottom, a palm, a board or a sun above,
    and the ridge pair at its left edge, across the waves."""

    bottom = -band_height / 2.0
    lines = [waves(bottom + 2.6, 1.3, 1.2), waves(bottom + 6.8, 1.3, 1.2)]

    room = band_height - 10.0                 # above the waves
    size = min(0.85 * room, 0.7 * panel_width)
    middle = bottom + 10.0 + room / 2.0
    kind = index % 3
    if kind == 0:
        motif = palm(0.0, middle, size, 1.0 if index % 2 == 0 else -1.0)
    elif kind == 1:
        motif = surfboard(0.0, middle, 0.95 * size, -18.0 if index % 2 == 0 else 18.0)
    else:
        motif = sun(0.0, middle, 0.8 * size)
    return union_all(lines + [motif] + edge_ridges())


PANEL_MAKERS = {"cabana": cabana_panel, "surf": surf_panel}


def texture_shape():

    # Panel 0's left edge at the back (+Y), where the seam is, so the
    # seam tends to hide by a stripe.
    pieces = []
    for index in range(panels):
        angle = 180.0 + 360.0 * (index + 0.5) / panels
        pieces.append(PANEL_MAKERS[TEXTURE](index).rotate((0, 0, 0), (0, 0, 1), angle))

    shell = revolve([
        (outer_radius(band_low) - 1.0, band_low),
        (outer_radius(band_low) + TEXTURE_RELIEF, band_low),
        (outer_radius(band_high) + TEXTURE_RELIEF, band_high),
        (outer_radius(band_high) - 1.0, band_high),
    ])
    return union_all(pieces).intersect(shell)


if TEXTURE != "none":
    print(f"Adding texture ({TEXTURE}, {panels} panels) ...")
    boot = boot.union(texture_shape())

airtag = airtag_shape()


# ============================================================
# FIT CHECK
# ============================================================

# The AirTag must sit in its pocket without touching the boot, and the
# bottle must not press on it.

bottle = bottle_shape(WALL_HEIGHT + 60.0, z0=floor_top)

if CHECK_FIT:
    print("Checking fit ...")

    tests = [("bottle presses on the AirTag", airtag, bottle)]
    if AIRTAG_CLEARANCE >= 0.0:
        tests.append(("AirTag hits the pocket", airtag, pocket_boot))
    else:
        print(f"  AirTag pressed in {-AIRTAG_CLEARANCE:g} tight on the diameter (not checked)")
    clashes = []

    for name, a, b in tests:
        overlap = volume(a.intersect(b))
        if overlap > 0.01:
            clashes.append(f"{name} ({overlap:.2f} mm3)")

    for clash in clashes:
        print(f"WARNING: overlap - {clash}")
    if not clashes:
        print("  no overlaps")


# ============================================================
# EXPORT (print orientation)
# ============================================================

if __name__ == "__main__":

    # As fitted: floor on the bed, open side up.
    parts = {
        "boot": to_bed(boot),
    }

    out_dir = PROFILE_DIR.resolve()
    written = []

    for name, shape in parts.items():
        filename = out_dir / f"{OUTPUT_PREFIX}_{name}.stl"
        cq.exporters.export(
            shape, str(filename),
            tolerance=STL_TOLERANCE, angularTolerance=STL_ANGULAR_TOLERANCE
        )
        written.append(filename.name)


# ============================================================
# PREVIEW IMAGE
# ============================================================

# Renders the boot on the bottle (fitted, exploded, section, from
# below) and the part as printed to a PNG so the design can be checked
# without a slicer.  Needs matplotlib; skipped if it is missing.

COLORS = {
    "boot": (0.20, 0.55, 0.62),
    "bottle": (0.70, 0.72, 0.75),
    "airtag": (0.93, 0.93, 0.93),
}


def mesh(shape, color):

    import numpy as np

    vertices, triangles = cq.Compound.makeCompound(shape.vals()).tessellate(0.05, 0.2)
    if not triangles:
        return np.zeros((0, 3, 3)), np.zeros((0, 3))
    xyz = np.array([(v.x, v.y, v.z) for v in vertices])
    tris = xyz[np.array(triangles, dtype=int)]

    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    normals = normals / np.where(lengths == 0.0, 1.0, lengths)[:, None]

    light = np.array([-0.4, -0.7, 0.6])
    light = light / np.linalg.norm(light)

    shade = 0.35 + 0.65 * np.abs(normals @ light)
    colors = shade[:, None] * np.array(color)

    return tris, colors


def half_section(ax, title):
    """Flat drawing of the half section with the bottle and AirTag."""

    import matplotlib.patches as patches

    r, z = zip(*outline(section))
    ax.fill(r, z, color=COLORS["boot"], zorder=2)

    bottle_top = top_z + 8.0
    corner = (bottle_flat, floor_top + CORNER_RADIUS)
    br, bz = zip(*outline([
        (0.0, floor_top),
        (bottle_flat, floor_top),
        ("arc", arc_middle(corner, CORNER_RADIUS, -90.0, 0.0), (base_radius, corner[1])),
        (bottle_radius(bottle_top - floor_top), bottle_top),
    ])[:-1])
    ax.plot(br, bz, color="0.45", linewidth=1.2, linestyle="--", zorder=3, label="bottle")

    ax.add_patch(patches.FancyBboxPatch(
        (0.0, FLOOR_UNDER), AIRTAG_DIAMETER / 2.0, AIRTAG_THICKNESS,
        boxstyle="round,pad=0,rounding_size=1.5",
        facecolor=COLORS["airtag"], edgecolor="0.4", zorder=3, label="AirTag"
    ))

    ax.axvline(0.0, color="0.6", linewidth=0.8, linestyle="-.")
    ax.set_xlim(-2.0, outer_radius(top_z) + 3.0)
    ax.set_ylim(-2.0, top_z + 10.0)
    ax.set_aspect("equal")
    ax.grid(True, linewidth=0.3)
    ax.tick_params(labelsize=7)
    ax.legend(fontsize=7, loc="upper left")
    ax.set_title(title, fontsize=10)


def render_preview(filename):

    import numpy as np
    import matplotlib

    matplotlib.use("Agg")

    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    lift = 30.0

    # Drawn a little inside the boot's wall, or the two show through
    # each other where the squeeze makes them overlap.
    shown = bottle_shape(WALL_HEIGHT + 60.0, squeeze=c + 0.3, z0=floor_top)

    fitted = [(boot, "boot"), (shown, "bottle")]
    exploded = [
        (boot, "boot"),
        (airtag.translate((0, 0, lift)), "airtag"),
        (bottle.translate((0, 0, 2.5 * lift)), "bottle"),
    ]

    # Cut through the axis, seen from the front, so the wall, the
    # pocket and the lip show.
    keep = box(-big, big, 0.0, big, -big, big)
    cut = [(shape.intersect(keep), name)
           for shape, name in [(boot, "boot"), (airtag, "airtag"), (shown, "bottle")]]

    views = [
        ("On the bottle", fitted, 20, -60),
        ("Exploded (AirTag goes in from the top)", exploded, 20, -60),
        ("From below", [(boot, "boot"), (airtag, "airtag")], -60, -60),
        ("Section", cut, 0, -90),
        ("Half section (mm)", None, 0, 0),
        ("Boot (as printed)", [(parts["boot"], "boot")], 35, -60),
    ]

    fig = plt.figure(figsize=(15, 10))

    for index, (title, items, elevation, azimuth) in enumerate(views):

        if items is None:
            half_section(fig.add_subplot(2, 3, index + 1), title)
            continue

        ax = fig.add_subplot(2, 3, index + 1, projection="3d")

        all_tris = []
        all_colors = []
        for shape, color_name in items:
            if not shape.vals():
                continue
            tris, colors = mesh(shape, COLORS[color_name])
            all_tris.append(tris)
            all_colors.append(colors)

        tris = np.concatenate(all_tris)
        colors = np.concatenate(all_colors)

        ax.add_collection3d(
            Poly3DCollection(tris, facecolors=colors, edgecolors="none")
        )

        lo = tris.reshape(-1, 3).min(axis=0)
        hi = tris.reshape(-1, 3).max(axis=0)
        centre = (lo + hi) / 2.0
        half = (hi - lo).max() / 2.0 + 1.0

        ax.set_xlim(centre[0] - half, centre[0] + half)
        ax.set_ylim(centre[1] - half, centre[1] + half)
        ax.set_zlim(centre[2] - half, centre[2] + half)
        ax.set_box_aspect((1, 1, 1))
        ax.set_proj_type("ortho")
        ax.view_init(elev=elevation, azim=azimuth)
        ax.set_axis_off()
        ax.set_title(title, fontsize=10)

    fig.suptitle(
        f"Bottle boot - {2.0 * outer_radius(top_z):.1f} mm across, {top_z:.1f} mm tall, "
        f"bottle raised {floor_top:.1f} mm, AirTag in the floor",
        fontsize=12
    )

    fig.tight_layout()
    fig.savefig(out_dir / filename, dpi=130)


if __name__ == "__main__" and PREVIEW:
    print("Rendering preview ...")
    try:
        render_preview(PREVIEW_FILE)
        written.append(PREVIEW_FILE)
    except ImportError:
        print("Preview skipped (python -m pip install matplotlib)")
    except Exception as error:
        print(f"WARNING: Preview failed: {error}")


# ============================================================
# FINAL REPORT
# ============================================================

if __name__ == "__main__":

    grams = volume(boot) / 1000.0 * TPU_DENSITY

    print()
    print("=============================================================")
    print("SUCCESS")
    print("=============================================================")
    print()
    print("Generated:")
    for name in written:
        print(f"  {name}")
    print()
    print("Geometry:")
    print(f"  Boot:           {2.0 * outer_radius(BOTTOM_ROUND):.1f} across at the bottom, "
          f"{2.0 * outer_radius(top_z):.1f} at the top, {top_z:.1f} tall")
    print(f"  Inside:         {2.0 * inner_radius(floor_top + CORNER_RADIUS):.1f} at the bottom, "
          f"{FIT_SQUEEZE:g} smaller than the bottle")
    print(f"  Floor:          {floor_top:.1f} thick (bottle raised by this), "
          f"{FLOOR_UNDER:g} under the AirTag")
    print(f"  AirTag pocket:  {2.0 * pocket_radius:.1f} across "
          f"({'press fit' if AIRTAG_CLEARANCE < 0 else 'clearance'} {abs(AIRTAG_CLEARANCE):g}), "
          f"{pocket_top - FLOOR_UNDER:.1f} deep"
          + (f", lip opening {2.0 * lip_radius:.1f}" if has_lip else ", no lip"))
    if SPRING_BUMPS:
        print(f"  Spring bumps:   {SPRING_BUMPS}, squashed {SPRING_HEIGHT - AIRTAG_HEADROOM:.1f} by the AirTag")
    print(f"  Holes:          push {PUSH_HOLE_DIAMETER:g}, {SOUND_HOLES} sound, "
          f"{DRAIN_HOLES} drain")
    print(f"  Weight:         {grams:.0f} g solid TPU (less with infill)")
    print()
    print("Press the AirTag in, white side up, then push the bottle in.")
    print("=============================================================")
