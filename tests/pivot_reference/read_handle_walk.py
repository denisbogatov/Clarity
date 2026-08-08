# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Turns a walk log into the table the walk was run for.

Reads the `stderr` of a `probe_clarity_pivot_handles.walk_the_axes` run - `PROBE` markers from the
probe, `draw_prepare:` and `pick:` lines from the gizmo trace - and prints, per axis and distance,
which handles the select buffer hit and which one it handed the press to.

Handles are matched by the `gz=` pointer both traces print, not by the id the select buffer uses:
that id indexes the visible gizmos of the frame, and which handles are visible changes with the
mode.

    python tests/pivot_reference/read_handle_walk.py gztrace.txt

Temporary, with the traces it reads.
"""

import re
import sys

PROBE = re.compile(r"^PROBE (.*)$")
STOP = re.compile(r"^mode=([\w.-]+) axis=(\w+) distance=(\d+) at=\((-?\d+) (-?\d+)\)$")
DUMP = re.compile(r"draw_prepare: (\w+)\s+gz=(0x[0-9a-fA-F]+|[0-9A-Fa-f]+) .*?reach=([\d.]+)px")
HIT = re.compile(r"pick: hotspot=(\d+) hits=(\d+) id=\d+ gz=(\S+) (\S+) depth=([\d.]+)")
LOOKED = re.compile(r"pick: at=\((-?\d+) (-?\d+)\) hotspot=(\d+) offered=(\d+) hits=(\d+)")
WINNER = re.compile(r"pick: winner rule=(\w+) id=(-?\d+) gz=(\S+) (\S+)")
DRAWSEL = re.compile(
    r"drawsel: id=(\d+) gz=(\S+) (\S+) scale=([-\d.]+) origin=\(([-\d. ]+)\) axis=\(([-\d. ]+)\)")


def read_lines(path):
    """The log, whichever encoding the shell that captured it chose."""
    data = open(path, "rb").read()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = data.decode("utf-16", "replace")
    else:
        text = data.decode("utf-8", "replace")
    # PowerShell wraps native output at the console width; a wrapped line is one that does not open
    # a record of its own.
    out = []
    for line in text.replace("\r", "").split("\n"):
        if line.startswith(("GZTRACE", "PROBE")) or not out:
            out.append(line)
        else:
            out[-1] += line
    return out


def main(path):
    names = {}
    reach = {}
    stop = None
    header = []
    rows = []
    hits = []
    drawn = []
    drawsel = {}
    looked = None
    winner = None

    def flush():
        if stop is None:
            return
        mode, axis, distance = stop
        seen = ["{:s}@{:s}".format(names.get(gz, gz), depth) for gz, depth in hits]
        rows.append((mode, axis, int(distance), looked, len(set(drawn)), seen,
                     names.get(winner[0], winner[0]) if winner else "-",
                     winner[1] if winner else "-"))

    for line in read_lines(path):
        match = DUMP.search(line)
        if match:
            names[match.group(2)] = match.group(1)
            reach[match.group(1)] = float(match.group(3))
            continue
        match = PROBE.match(line)
        if match:
            body = match.group(1)
            stop_match = STOP.match(body)
            if stop_match:
                flush()
                stop = (stop_match.group(1), stop_match.group(2), stop_match.group(3))
                hits = []
                drawn = []
                looked = None
                winner = None
            else:
                flush()
                stop = None
                header.append(body)
            continue
        match = DRAWSEL.search(line)
        if match:
            drawn.append(match.group(2))
            drawsel.setdefault(
                match.group(2),
                (match.group(3), float(match.group(4)), match.group(5), match.group(6)))
            continue
        match = LOOKED.search(line)
        if match and stop is not None:
            looked = (match.group(1), match.group(2))
            continue
        match = HIT.search(line)
        if match and stop is not None:
            hits.append((match.group(3), match.group(5)))
            continue
        match = WINNER.search(line)
        if match and stop is not None:
            winner = (match.group(3), match.group(1))
    flush()

    for line in header:
        print("# " + line)
    if reach:
        print("#")
        print("# handle reach in pixels, from the last draw_prepare dump:")
        for name, value in sorted(reach.items(), key=lambda item: -item[1]):
            if value > 0.0:
                print("#   {:<9s} {:.0f}".format(name, value))
    if drawsel:
        print("#")
        print("# what each handle drew into the select buffer, world space:")
        for gz, (idname, scale, origin, axis) in sorted(
                drawsel.items(), key=lambda item: names.get(item[0], item[0])):
            print("#   {:<9s} {:<22s} scale={:.3f} origin=({:s}) axis=({:s})".format(
                names.get(gz, gz), idname, scale, origin, axis))
    print()
    print("{:<14s} {:<5s} {:>9s} {:>11s} {:>6s}  {:<10s} {:<8s} {:s}".format(
        "mode", "axis", "distance", "looked at", "drawn", "winner", "rule", "hits"))
    for mode, axis, distance, looked_at, drawn_count, seen, won, rule in rows:
        print("{:<14s} {:<5s} {:>7d}px {:>11s} {:>6d}  {:<10s} {:<8s} {:s}".format(
            mode, axis, distance,
            "{:s},{:s}".format(*looked_at) if looked_at else "-",
            drawn_count, won, rule, " ".join(seen) if seen else "-"))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
