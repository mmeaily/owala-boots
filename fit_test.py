"""
Bottle boot fit test pieces
===========================

Small pieces of the real boot, built by generate.py from a bottle
profile, so the bottle measurements and the AirTag pocket can be
checked before printing the whole boot (each piece is a few minutes).

    fit_ring    the bottom of the wall with a rim of floor: push the
                bottle into it; checks BASE_DIAMETER, CORNER_RADIUS
                and the grip (FIT_SQUEEZE)
    fit_pocket  the middle of the floor with the AirTag pocket, its
                lip and the holes: checks the AirTag presses in past
                the lip, stays put, and pushes out from below

Run:
    python fit_test.py bottles/<name>

Output (fit_test/ in the profile's folder):
    fit_test_plate.stl   both pieces side by side, ready to print
    fit_<name>.stl       the same, one piece at a time

The ring should need a firm push to go on and not turn easily.  Too
loose: raise FIT_SQUEEZE or lower BASE_DIAMETER; too tight, the other
way.  Correct the profile's bottle.json and run again.
"""

# Reads the profile from the command line, as when run directly.
import generate as g


OUT_DIR = g.PROFILE_DIR / "fit_test"
RING_HEIGHT = 12.0
RIM = 3.0


def ring(shape):
    """Wall from just under the floor top up RING_HEIGHT, with a rim of floor."""

    band = shape.intersect(
        g.box(-g.big, g.big, -g.big, g.big, g.floor_top - 1.5, g.floor_top + RING_HEIGHT)
    )
    return g.to_bed(band.cut(g.cylinder_z(g.inner_flat - RIM, -g.big, g.big)))


def pocket(shape):
    """Disc of floor round the AirTag pocket."""

    return g.to_bed(shape.intersect(g.cylinder_z(g.pocket_radius + 4.0, -g.big, g.floor_top)))


def main():

    OUT_DIR.mkdir(exist_ok=True)

    pieces = {
        "ring": ring(g.boot),
        "pocket": pocket(g.boot),
    }

    plate = None
    row_x = 0.0

    for name, piece in pieces.items():
        bb = piece.val().BoundingBox()
        piece = piece.translate((-bb.xmin, -bb.ymin, 0))
        g.cq.exporters.export(piece, str(OUT_DIR / f"fit_{name}.stl"),
                               tolerance=g.STL_TOLERANCE, angularTolerance=g.STL_ANGULAR_TOLERANCE)
        moved = piece.translate((row_x, 0, 0))
        plate = moved if plate is None else plate.union(moved)
        row_x += bb.xlen + 6.0
        print(f"  fit_{name}: {bb.xlen:.0f} x {bb.ylen:.0f} x {bb.zlen:.0f} mm")

    g.cq.exporters.export(plate, str(OUT_DIR / "fit_test_plate.stl"),
                           tolerance=g.STL_TOLERANCE, angularTolerance=g.STL_ANGULAR_TOLERANCE)
    print(f"Wrote {OUT_DIR / 'fit_test_plate.stl'} and one STL per piece")


if __name__ == "__main__":
    main()
