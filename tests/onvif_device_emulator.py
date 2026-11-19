#!/usr/bin/env python3
"""Shared synthetic ONVIF device: Linux registry contracts and the installed Windows gate.

Test-only. It answers exactly the SOAP shapes the packaged Camera Registry parses, with
WS-Security and optional HTTP digest checks, so device operations (probe, sync, presets,
PTZ move/stop, snapshot, user management) can be proved end to end without a physical
camera. It is not real-device qualification.
"""

from __future__ import annotations

import base64
import hashlib
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import parse_http_list, parse_keqv_list


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]



def build_handler(registry):
    """Bind the emulator to one loaded Camera Registry module.

    The handler needs the registry's own XML guard (``parse_onvif_xml``,
    ``MAX_ONVIF_XML``, ``OnvifError``) so the device rejects exactly what the
    product rejects instead of trusting a second parser.
    """

    class OnvifEmulatorHandler(BaseHTTPRequestHandler):
        profile_kind = "T"
        require_http_digest = False
        username = "test-operator"
        password = "fixture-password"
        action_log: list[str] = []
        ptz_moves: list[str] = []
        snapshot_reads = 0
        ptz_configuration_token = ""
        ptz_timeout_min = "PT0.1S"
        ptz_timeout_max = "PT2S"
        device_clock_offset = 0
        scheme = "http"
        users: dict[str, str] = {username: "Administrator"}

        def log_message(self, format: str, *args: object) -> None:
            return

        def soap(self, body: str, status: int = 200) -> None:
            if self.ptz_configuration_token and 'GetProfilesResponse' in body:
                profiles = ET.fromstring(body)
                for profile in profiles.iter():
                    if local_name(profile.tag) != 'Profiles': continue
                    configurations = next((node for node in profile if local_name(node.tag) == 'Configurations'), None)
                    parent = configurations if configurations is not None else profile
                    tag = '{http://www.onvif.org/ver20/media/wsdl}PTZ' if configurations is not None else '{http://www.onvif.org/ver10/schema}PTZConfiguration'
                    ET.SubElement(parent, tag, {'token': self.ptz_configuration_token})
                body = ET.tostring(profiles, encoding='unicode')
            data = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
                    '<s:Body>' + body + '</s:Body></s:Envelope>').encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/soap+xml")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True

        def authenticated(self, root: ET.Element) -> bool:
            token = next((node for node in root.iter()
                          if local_name(node.tag) == "UsernameToken"), None)
            values = {local_name(node.tag): (node.text or "") for node in token.iter()} \
                if token is not None else {}
            try:
                nonce = base64.b64decode(values["Nonce"], validate=True)
                expected = base64.b64encode(hashlib.sha1(
                    nonce + values["Created"].encode() + self.password.encode()).digest()).decode()
                return values.get("Username") == self.username and values.get("Password") == expected
            except (KeyError, ValueError):
                return False

        def digest_authenticated(self) -> bool:
            authorization = self.headers.get("Authorization", "")
            if len(authorization) > 8192 or not authorization.startswith("Digest "):
                return False
            try:
                values = parse_keqv_list(parse_http_list(authorization[7:]))
                ha1 = hashlib.md5(f'{self.username}:webobs-fixture:{self.password}'.encode()).hexdigest()
                ha2 = hashlib.md5(f'POST:{values["uri"]}'.encode()).hexdigest()
                expected = hashlib.md5(
                    f'{ha1}:fixture-nonce:{values["nc"]}:{values["cnonce"]}:auth:{ha2}'.encode()).hexdigest()
                return values.get("username") == self.username and values.get("response") == expected
            except (KeyError, ValueError):
                return False

        def do_GET(self) -> None:
            if self.path == "/snapshot.jpg":
                # Counted so a caller can prove a denied snapshot never fetched bytes.
                type(self).snapshot_reads += 1
                data = b"\xff\xd8\xff\xe0webobs-fixture\xff\xd9"
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= registry.MAX_ONVIF_XML:
                    raise ValueError("invalid fixture request size")
                root = registry.parse_onvif_xml(self.rfile.read(length))
            except (ValueError, registry.OnvifError):
                self.send_error(400)
                return
            action = self.headers.get("SOAPAction", "") + " " + self.headers.get("Content-Type", "")
            if "GetSystemDateAndTime" in action:
                current = datetime.now(timezone.utc) + timedelta(seconds=self.device_clock_offset)
                self.soap('<tds:GetSystemDateAndTimeResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema"><tds:SystemDateAndTime><tt:UTCDateTime><tt:Time>'
                          f'<tt:Hour>{current.hour}</tt:Hour><tt:Minute>{current.minute}</tt:Minute><tt:Second>{current.second}</tt:Second>'
                          '</tt:Time><tt:Date>'
                          f'<tt:Year>{current.year}</tt:Year><tt:Month>{current.month}</tt:Month><tt:Day>{current.day}</tt:Day>'
                          '</tt:Date></tt:UTCDateTime></tds:SystemDateAndTime></tds:GetSystemDateAndTimeResponse>')
                return
            if self.require_http_digest and not self.digest_authenticated():
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Digest realm="webobs-fixture", nonce="fixture-nonce", algorithm=MD5, qop="auth"')
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                return
            if not self.authenticated(root):
                self.soap('<s:Fault xmlns:s="http://www.w3.org/2003/05/soap-envelope"/>', 403)
                return
            self.action_log.append(action)
            port = self.server.server_address[1]
            base = f"{self.scheme}://127.0.0.1:{port}"
            if "GetServices" in action:
                media_services = (f'<tds:Service><tds:Namespace>http://www.onvif.org/ver20/media/wsdl</tds:Namespace><tds:XAddr>{base}/media2</tds:XAddr></tds:Service>'
                                  if self.profile_kind == "T" else "")
                media_services += f'<tds:Service><tds:Namespace>http://www.onvif.org/ver10/media/wsdl</tds:Namespace><tds:XAddr>{base}/media1</tds:XAddr></tds:Service>'
                self.soap('<tds:GetServicesResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl">' + media_services +
                          f'<tds:Service><tds:Namespace>http://www.onvif.org/ver20/ptz/wsdl</tds:Namespace><tds:XAddr>{base}/ptz</tds:XAddr></tds:Service>'
                          f'<tds:Service><tds:Namespace>http://www.onvif.org/ver10/events/wsdl</tds:Namespace><tds:XAddr>{base}/events</tds:XAddr></tds:Service>'
                          '</tds:GetServicesResponse>')
            elif "GetProfiles" in action:
                if self.profile_kind == "T" and self.path == "/media2":
                    self.soap('<tr2:GetProfilesResponse xmlns:tr2="http://www.onvif.org/ver20/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">'
                              '<tr2:Profiles token="profile-main"><tr2:Name>Main stream</tr2:Name><tr2:Configurations><tr2:VideoEncoder><tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>1920</tt:Width><tt:Height>1080</tt:Height></tt:Resolution><tt:RateControl><tt:FrameRateLimit>25</tt:FrameRateLimit></tt:RateControl></tr2:VideoEncoder><tr2:AudioEncoder><tt:Encoding>AAC</tt:Encoding></tr2:AudioEncoder></tr2:Configurations></tr2:Profiles>'
                              '<tr2:Profiles token="profile-sub"><tr2:Name>Sub stream</tr2:Name><tr2:Configurations><tr2:VideoEncoder><tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>640</tt:Width><tt:Height>360</tt:Height></tt:Resolution><tt:Framerate>15</tt:Framerate></tr2:VideoEncoder></tr2:Configurations></tr2:Profiles>'
                              '</tr2:GetProfilesResponse>')
                else:
                    self.soap('<trt:GetProfilesResponse xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">'
                              '<trt:Profiles token="legacy-main"><tt:Name>Legacy stream</tt:Name><tt:VideoEncoderConfiguration><tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>1280</tt:Width><tt:Height>720</tt:Height></tt:Resolution><tt:RateControl><tt:FrameRateLimit>20</tt:FrameRateLimit></tt:RateControl></tt:VideoEncoderConfiguration></trt:Profiles>'
                              '</trt:GetProfilesResponse>')
            elif "GetConfigurationOptions" in action and '/ptz/' in action:
                self.soap('<tptz:GetConfigurationOptionsResponse xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">'
                          '<tptz:PTZConfigurationOptions><tt:PTZTimeout><tt:Min>' + self.ptz_timeout_min +
                          '</tt:Min><tt:Max>' + self.ptz_timeout_max + '</tt:Max></tt:PTZTimeout>'
                          '</tptz:PTZConfigurationOptions></tptz:GetConfigurationOptionsResponse>')
            elif "GetStreamUri" in action:
                token = next((node.text for node in root.iter() if local_name(node.tag) == "ProfileToken"), "stream")
                self.soap('<trt:GetStreamUriResponse xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema"><trt:MediaUri><tt:Uri>'
                          f'rtsp://camera.example.invalid/{token}'
                          '</tt:Uri></trt:MediaUri></trt:GetStreamUriResponse>')
            elif "GetSnapshotUri" in action:
                self.soap('<trt:GetSnapshotUriResponse xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema"><trt:MediaUri><tt:Uri>' + base + '/snapshot.jpg</tt:Uri></trt:MediaUri></trt:GetSnapshotUriResponse>')
            elif "GetAudioDecoderConfigurationOptions" in action:
                self.soap('<tr2:GetAudioDecoderConfigurationOptionsResponse xmlns:tr2="http://www.onvif.org/ver20/media/wsdl"/>')
            elif "GetUsers" in action:
                users = "".join(
                    '<tds:User><tt:Username>' + username + '</tt:Username><tt:UserLevel>' + level +
                    '</tt:UserLevel></tds:User>' for username, level in sorted(self.users.items()))
                self.soap('<tds:GetUsersResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl" '
                          'xmlns:tt="http://www.onvif.org/ver10/schema">' + users +
                          '</tds:GetUsersResponse>')
            elif "CreateUsers" in action or "SetUser" in action:
                fields = {local_name(node.tag): (node.text or "") for node in root.iter()}
                account, level = fields.get("Username", ""), fields.get("UserLevel", "")
                if not account or level not in {"User", "Operator"}:
                    self.soap('<s:Fault xmlns:s="http://www.w3.org/2003/05/soap-envelope"/>', 400)
                else:
                    self.users[account] = level
                    self.soap('<tds:UserMutationResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl"/>')
            elif "DeleteUsers" in action:
                usernames = [node.text or "" for node in root.iter()
                             if local_name(node.tag) == "Username"]
                account = usernames[-1] if usernames else ""
                if account != self.username:
                    self.users.pop(account, None)
                self.soap('<tds:DeleteUsersResponse xmlns:tds="http://www.onvif.org/ver10/device/wsdl"/>')
            elif "GetPresets" in action:
                self.soap('<tptz:GetPresetsResponse xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema"><tptz:Preset token="preset-1"><tt:Name>Entrance</tt:Name></tptz:Preset></tptz:GetPresetsResponse>')
            elif "SetPreset" in action:
                self.soap('<tptz:SetPresetResponse xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"><tptz:PresetToken>preset-created</tptz:PresetToken></tptz:SetPresetResponse>')
            elif any(name in action for name in ("ContinuousMove", "RelativeMove", "AbsoluteMove", "Stop", "GotoHomePosition", "GotoPreset", "RemovePreset")):
                if 'ContinuousMove' in action: self.ptz_moves.append(next((node.text or '' for node in root.iter() if local_name(node.tag) == 'Timeout'), ''))
                self.soap('<tptz:OperationResponse xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"/>')
            elif "CreatePullPointSubscription" in action:
                self.soap('<tev:CreatePullPointSubscriptionResponse xmlns:tev="http://www.onvif.org/ver10/events/wsdl" xmlns:wsa="http://www.w3.org/2005/08/addressing"><tev:SubscriptionReference><wsa:Address>' + base + '/pullpoint</wsa:Address></tev:SubscriptionReference></tev:CreatePullPointSubscriptionResponse>')
            elif "PullMessages" in action:
                self.soap('<tev:PullMessagesResponse xmlns:tev="http://www.onvif.org/ver10/events/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema"><tev:NotificationMessage><tev:Topic>tns1:RuleEngine/CellMotionDetector/Motion</tev:Topic><tev:Message><tt:Message><tt:Data><tt:SimpleItem Name="IsMotion" Value="true"/></tt:Data></tt:Message></tev:Message></tev:NotificationMessage></tev:PullMessagesResponse>')
            else:
                self.soap('<s:Fault xmlns:s="http://www.w3.org/2003/05/soap-envelope"/>', 500)


    return OnvifEmulatorHandler


def start(registry, **attributes):
    """Serve one synthetic device on a loopback port chosen by the OS."""
    handler = type("OnvifEmulatorDevice", (build_handler(registry),), dict(attributes))
    server = HTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    return server, worker, handler, f"http://127.0.0.1:{server.server_address[1]}"
