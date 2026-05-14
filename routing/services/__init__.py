# On some hosts (notably macOS dev boxes without working IPv6), urllib3's
# default "happy eyeballs" path tries an AAAA record first and waits ~20s
# for it to fail before retrying over IPv4 — which dominates our request
# time end-to-end (the OSRM call goes from ~1.5s to ~21s). curl picks IPv4
# first by default, which is why it never showed the slowness.
#
# Forcing urllib3 to pretend IPv6 isn't available makes it skip the AAAA
# attempt entirely. Harmless on real IPv6-enabled hosts; the OSRM and
# Nominatim demos are dual-stack and serve identical responses over v4.
import urllib3.util.connection

urllib3.util.connection.HAS_IPV6 = False
