#!/usr/bin/env python3

# Copyright 2023 The Autoware Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This script requires "source install/setup.bash" for dependent messages/services.

import shutil
import yaml
from pathlib import Path

from rosidl_adapter.parser import MessageSpecification
from rosidl_adapter.parser import parse_message_file
from rosidl_adapter.parser import parse_service_file
from ament_index_python.packages import get_package_share_directory


# cSpell:words indentless
class MyDumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, *args, **kwargs):
        return super().increase_indent(flow=flow, indentless=False)


def load_markdown_metadata(path: Path):
    lines = path.read_text().splitlines()
    if (2 < len(lines)) and (lines[0] == "---"):
        data = lines[1:lines.index("---", 1)]
        data = yaml.safe_load("\n".join(data))
        return test_markdown_metadata(data, path)
    return None


def test_markdown_metadata(data, path):
    if "status" not in data:
        raise KeyError(f"status in {path}")
    return data


def is_documentation_msg(name: str):
    targets = set(["autoware_adapi_version_msgs", "autoware_adapi_v1_msgs"])
    return name.split("/")[0] in targets


def strip_array_suffix(name: str):
    return name.split("[")[0]


def resolve_msg_file_path(name: str):
    pkg, ext, msg = name.split("/")
    return Path(get_package_share_directory(pkg)).joinpath(ext, msg).with_suffix("." + ext)


def normalize_msg_name(name: str):
    parts = str(name).split("/")
    return parts[0] if len(parts) == 1 else f"{parts[0]}/msg/{parts[1]}"


def parse_rosidl_spec(depends: set, visited: set, spec: MessageSpecification):
    fields = {field.name: normalize_msg_name(field.type) for field in spec.fields}
    for name in fields.values():
        name = strip_array_suffix(name)
        if name not in visited:
            depends.add(name)
    return fields


def parse_rosidl_file(depends: set, visited: set, specs: dict, name: str):
    visited.add(name)
    if is_documentation_msg(name):
        pkg, ext, msg = name.split("/")
        if ext == "msg":
            msg = parse_message_file(pkg, resolve_msg_file_path(name))
            msg = parse_rosidl_spec(depends, visited, msg)
            specs[name] = {"msg": msg}
            specs[name] = {k: v for k, v in specs[name].items() if v}
        if ext == "srv":
            srv = parse_service_file(pkg, resolve_msg_file_path(name))
            req = parse_rosidl_spec(depends, visited, srv.request)
            res = parse_rosidl_spec(depends, visited, srv.response)
            specs[name] = {"req": req, "res": res}
            specs[name] = {k: v for k, v in specs[name].items() if v}


def tabulate(data, header):
    widths = map(len, header)
    for line in data:
        widths = map(max, zip(map(len, line), widths))
    widths = list(widths)
    format = "| " + " | ".join(f"{{:{width}}}" for width in widths) + " |"
    border = ["-" * width for width in widths]
    return "\n".join(format.format(*line) for line in [header, border, *data])


def main():
    # Create a list of data types used in adapi.
    adapi = Path("docs/design/autoware-interfaces/ad-api/list/api")
    pages = (load_markdown_metadata(path) for path in adapi.glob("**/*.md"))
    pages = [page for page in pages if page]

    # Create a field list for each data type.
    names = (page["type"]["name"] for page in pages)
    specs = {}
    visited = set()
    depends = set(names)
    while depends:
        name = depends.pop()
        parse_rosidl_file(depends, visited, specs, name)

    # Export a field list.
    data = {"types": specs}
    Path("yaml/autoware-interfaces.yaml").write_text(yaml.dump(data, Dumper=MyDumper))

    # Create data type dependencies.
    type_uses = {name: set() for name in specs}
    type_used = {name: set() for name in specs}
    for user, spec in specs.items():
        for field in spec.values():
            for name in field.values():
                name = strip_array_suffix(name)
                if is_documentation_msg(name):
                    type_uses[user].add(name)
                    type_used[name].add(user)

    # Clean up data type pages.
    base = Path("docs/design/autoware-interfaces/ad-api/types")
    for path in base.iterdir():
        if path.is_dir():
            shutil.rmtree(path)

    # Generate data type pages.
    for name in specs:
        uses = list(sorted(type_uses[name]))
        used = list(sorted(type_used[name]))
        data = {"title": name, "uses": uses, "used": used}
        data = {k: v for k, v in data.items() if v}
        text = "---\n"
        text += "# This file is generated by tools/autoware-interfaces/generate.py\n"
        text += yaml.dump(data, Dumper=MyDumper).strip() + "\n"
        text += "---\n\n"
        text += "{% extends 'design/autoware-interfaces/templates/autoware-data-type.jinja2' %}\n"
        text += "{% block definition %}\n"
        text += "\n```txt\n"
        text += resolve_msg_file_path(name).read_text().strip() + "\n"
        text += "```\n\n"
        text += "{% endblock %}\n"
        path = base.joinpath(name).with_suffix(".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    ## Generate api list page.
    data = []
    for page in sorted(pages, key=lambda page: page["title"]):
        title = page["title"]
        data.append([f"[{title}](.{title}.md)", page['status']])
    text = "# List of Autoware AD API\n\n" + tabulate(data, ["API", "Release"]) + "\n"
    Path("docs/design/autoware-interfaces/ad-api/list/index.md").write_text(text)

    ## Generate api type page.
    text = "# Types of Autoware AD API\n\n"
    for spec in sorted(specs):
        text += f"- [{spec}](./{spec}.md)\n"
    Path("docs/design/autoware-interfaces/ad-api/types/index.md").write_text(text)

main()
