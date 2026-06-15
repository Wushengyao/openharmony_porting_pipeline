#!/usr/bin/env python3
"""Generate a minimal OpenHarmony xDevice user_config.xml."""

from __future__ import annotations

import argparse
import sys
import xml.dom.minidom
import xml.etree.ElementTree as ET
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sn", default="")
    parser.add_argument("--device-type", default="usb-hdc")
    parser.add_argument("--ip", default="")
    parser.add_argument("--port", default="")
    parser.add_argument("--testcases-dir", default="")
    parser.add_argument("--resource-dir", default="")
    args = parser.parse_args()

    root = ET.Element("user_config")
    env = ET.SubElement(root, "environment")
    support = ET.SubElement(env, "support_device")
    ET.SubElement(support, "device").text = "true"
    device = ET.SubElement(env, "device", {"type": args.device_type})
    ET.SubElement(device, "ip").text = args.ip
    ET.SubElement(device, "port").text = args.port
    ET.SubElement(device, "sn").text = args.sn
    testcases = ET.SubElement(root, "testcases")
    ET.SubElement(testcases, "dir").text = args.testcases_dir
    resource = ET.SubElement(root, "resource")
    ET.SubElement(resource, "dir").text = args.resource_dir

    raw = ET.tostring(root, encoding="utf-8")
    pretty = xml.dom.minidom.parseString(raw).toprettyxml(indent="    ", encoding="UTF-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(pretty)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
