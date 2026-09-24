# Security policy

## Supported versions

Only the latest release of `christie-mseries` receives fixes.

## Reporting a vulnerability

Please report security problems privately, using GitHub's private vulnerability
reporting: open the **Security** tab of this repository and choose **Report a
vulnerability** (or go to <https://github.com/imsatasia/py-christie-mseries/security/advisories/new>).
Please do not open a public issue for a vulnerability.

This project is maintained by one person in their spare time, so this is
best-effort: I aim to acknowledge a report within a week and to say what I plan
to do about it shortly after.

## In scope

Bugs in this library that let untrusted input do something unintended, for example: building a message that smuggles a second command past the wire framing (`build_message` is meant to prevent this), unsafe handling of a malformed or hostile reply from a device, or crashes and unbounded resource use triggered by network data. The `examples/dump_menu.py` script talks to the projector's web interface over plain HTTP with the login you give it, so use it only on a trusted network.

## Out of scope

- Vulnerabilities in the projector's own firmware: report those to Christie.
- Vulnerabilities in Python itself or your operating system: report those to the upstream project.
- Advisories in test-only dependencies. Dependabot tracks those publicly and
  none of them ship in a release.

## Deployment note

When this project was tested, the projector's serial API on TCP 3002 accepted commands with no credentials, and nothing here adds authentication or encryption on top. Keep the projector on a trusted network and do not expose port 3002 to the internet.

## Please leave your device details out

Please do not include real IP addresses, serial numbers or MAC addresses of your
devices in reports, issues or pull requests. Placeholders such as `192.0.2.50` are
fine.
