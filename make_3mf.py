"""
Bambu Studio projects for the boot
==================================

Packs a profile's STLs (written by generate.py and fit_test.py) into
Bambu Studio project files set up for TPU 90A on the A1, so they open
ready to slice:

    <name>_boot.3mf             one boot, middle of the plate
    fit_test/fit_test.3mf       the fit test pieces (if fit_test.py ran)

Settings: bambu/a1_project_settings.config (the A1 project settings
from the scope lock), filament 1 replaced by the Bambu Studio system
preset named in bambu/tpu90a_boot.json, then that file's "print" and
"filament" settings on top.  The system presets are read from the
Bambu Studio install (BAMBU_SYSTEM below).

Run:
    python make_3mf.py bottles/<name>

Printing: TPU 90A will not go through the AMS lite.  Feed it from the
external spool and map filament 1 to it ("Ext") when sending.
"""

import json
import os
import sys
import uuid
import zipfile
from pathlib import Path

import numpy as np


HERE = Path(__file__).parent
TEMPLATE = HERE / "bambu" / "a1_project_settings.config"
OVERRIDES = HERE / "bambu" / "tpu90a_boot.json"
BAMBU_SYSTEM = Path(os.environ.get("APPDATA", "")) / "BambuStudio" / "system" / "BBL"
APPLICATION = "BambuStudio-02.08.02.61"
BED_CENTRE = (128.0, 128.0)       # A1, 256 x 256
SLOTS = 4                         # filament slots in the template


# ============================================================
# SETTINGS
# ============================================================

def without_notes(group):

    return {key: value for key, value in group.items() if not key.startswith("_")}


def system_preset(kind, name):
    """A system preset with everything it inherits, as one flat dict."""

    path = BAMBU_SYSTEM / kind / f"{name}.json"
    try:
        with open(path, encoding="utf-8") as file:
            preset = json.load(file)
    except FileNotFoundError:
        sys.exit(f"Bambu Studio preset not found: {path}")

    parent = preset.get("inherits")
    merged = system_preset(kind, parent) if parent else {}
    merged.update(preset)
    return merged


def per_filament(value):
    """A per-filament value as its list for one slot."""

    return value if isinstance(value, list) else [value]


def set_slot(settings, key, values, slot=0):
    """Put one filament's values into slot of a per-filament list."""

    current = settings.get(key)
    if not isinstance(current, list) or len(current) % SLOTS:
        return False
    width = len(current) // SLOTS
    if len(values) != width:
        return False
    settings[key] = current[:slot * width] + values + current[(slot + 1) * width:]
    return True


def project_settings():

    with open(TEMPLATE, encoding="utf-8") as file:
        settings = json.load(file)
    with open(OVERRIDES, encoding="utf-8") as file:
        overrides = json.load(file)

    name = overrides["FILAMENT_PRESET"]
    preset = system_preset("filament", name)

    skipped = []
    for key, value in preset.items():
        if key in ("name", "inherits", "from", "instantiation", "type", "setting_id",
                   "filament_id", "description", "compatible_printers"):
            continue
        if not set_slot(settings, key, per_filament(value)):
            skipped.append(key)

    set_slot(settings, "filament_settings_id", [name])
    set_slot(settings, "filament_ids", [preset["filament_id"]])

    for key, value in without_notes(overrides["filament"]).items():
        if not set_slot(settings, key, per_filament(value)):
            sys.exit(f"{OVERRIDES}: '{key}' is not a per-filament setting")

    for key, value in without_notes(overrides["print"]).items():
        if key not in settings:
            sys.exit(f"{OVERRIDES}: unknown print setting '{key}'")
        settings[key] = value

    if skipped:
        print(f"  preset keys left as they were: {', '.join(sorted(skipped))}")

    return settings, name


# ============================================================
# MESH
# ============================================================

def read_stl(path):
    """Binary STL to (vertices, triangles), shared vertices merged."""

    data = path.read_bytes()
    count = int.from_bytes(data[80:84], "little")
    if len(data) != 84 + 50 * count:
        sys.exit(f"{path}: not a binary STL")
    records = np.frombuffer(data, dtype=np.dtype([
        ("normal", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")
    ]), count=count, offset=84)

    corners = records["v"].reshape(-1, 3).astype(np.float64)
    vertices, index = np.unique(np.round(corners, 5), axis=0, return_inverse=True)
    return vertices, index.reshape(-1, 3)


def object_model(vertices, triangles, object_id):

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
        'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" '
        'requiredextensions="p">',
        ' <metadata name="BambuStudio:3mfVersion">1</metadata>',
        ' <resources>',
        f'  <object id="{object_id}" p:UUID="{uuid.uuid4()}" type="model">',
        '   <mesh>',
        '    <vertices>',
    ]
    lines += [f'     <vertex x="{x:.6g}" y="{y:.6g}" z="{z:.6g}"/>' for x, y, z in vertices]
    lines += ['    </vertices>', '    <triangles>']
    lines += [f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in triangles]
    lines += ['    </triangles>', '   </mesh>', '  </object>', ' </resources>', ' <build/>', '</model>']
    return "\n".join(lines)


# ============================================================
# PROJECT FILE
# ============================================================

def write_project(stl, out, settings, preset_name):
    """One object from stl, centred on plate 1."""

    vertices, triangles = read_stl(stl)
    lo, hi = vertices.min(axis=0), vertices.max(axis=0)
    centre = (lo + hi) / 2.0
    vertices = vertices - centre          # Bambu keeps meshes centred on their origin
    lift = (hi[2] - lo[2]) / 2.0
    name = stl.name

    # Ids: 1 the mesh, 2 the object on the plate that uses it.
    place = f"1 0 0 0 1 0 0 0 1 {BED_CENTRE[0]:g} {BED_CENTRE[1]:g} {lift:.6g}"

    main_model = f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">
 <metadata name="Application">{APPLICATION}</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <metadata name="Title">{stl.stem}</metadata>
 <resources>
  <object id="2" p:UUID="{uuid.uuid4()}" type="model">
   <components>
    <component p:path="/3D/Objects/object_1.model" objectid="1" p:UUID="{uuid.uuid4()}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>
   </components>
  </object>
 </resources>
 <build p:UUID="{uuid.uuid4()}">
  <item objectid="2" p:UUID="{uuid.uuid4()}" transform="{place}" printable="1"/>
 </build>
</model>
"""

    model_settings = f"""<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="2">
    <metadata key="name" value="{name}"/>
    <metadata key="extruder" value="1"/>
    <metadata face_count="{len(triangles)}"/>
    <part id="1" subtype="normal_part">
      <metadata key="name" value="{name}"/>
      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>
      <metadata key="source_file" value="{name}"/>
      <metadata key="source_object_id" value="0"/>
      <metadata key="source_volume_id" value="0"/>
      <mesh_stat face_count="{len(triangles)}" edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>
    </part>
  </object>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value="{preset_name}"/>
    <metadata key="locked" value="false"/>
    <model_instance>
      <metadata key="object_id" value="2"/>
      <metadata key="instance_id" value="0"/>
      <metadata key="identify_id" value="100"/>
    </model_instance>
  </plate>
  <assemble>
   <assemble_item object_id="2" instance_id="0" transform="{place}" offset="0 0 0" />
  </assemble>
</config>
"""

    files = {
        "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="png" ContentType="image/png"/>
 <Default Extension="gcode" ContentType="text/x.gcode"/>
</Types>""",
        "_rels/.rels": """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>""",
        "3D/_rels/3dmodel.model.rels": """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/Objects/object_1.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>""",
        "3D/3dmodel.model": main_model,
        "3D/Objects/object_1.model": object_model(vertices, triangles, 1),
        "Metadata/model_settings.config": model_settings,
        "Metadata/project_settings.config": json.dumps(settings, indent=4),
        "Metadata/slice_info.config": """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
    <header_item key="X-BBL-Client-Version" value="02.08.02.61"/>
  </header>
</config>""",
    }

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, text in files.items():
            archive.writestr(path, text)

    print(f"  {out}  ({len(triangles)} triangles)")


def main():

    if len(sys.argv) < 2:
        sys.exit("Name a bottle profile: bottles/<name>")
    profile = Path(sys.argv[1])
    if profile.name == "bottle.json":
        profile = profile.parent
    name = profile.resolve().name

    settings, preset_name = project_settings()

    jobs = [
        (profile / f"{name}_boot.stl", profile / f"{name}_boot.3mf"),
        (profile / "fit_test" / "fit_test_plate.stl", profile / "fit_test" / "fit_test.3mf"),
    ]

    for stl, out in jobs:
        if stl.exists():
            write_project(stl, out, settings, preset_name)
        else:
            print(f"  skipped {out.name}: no {stl} (run generate.py / fit_test.py)")


if __name__ == "__main__":
    main()
