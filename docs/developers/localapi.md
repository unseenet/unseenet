# Local client API

The local client API lets a program in **any language** use Unseenet: it
talks HTTP and a WebSocket to a client runtime on `127.0.0.1`, and the
runtime does the rest through `Session`. The graphical client and the web
client are built on it.

- **The protocol** - the requests, their JSON, the events and how a program
  authenticates - is [UN-RFC 0046](../spec/un-rfc-0046.md). Read that to
  write a client.
- **Running it for a program** (a service with its own key, section 3.2):
  `unseenet serve`. For a person's vault, the graphical client starts it.

This page is the Python side: `LocalAPI` in `unseenet.client.localapi`, what
answers each request before `server.py` puts it on HTTP. Its code follows the
sections of UN-RFC 0046, one part each, so a section of the RFC and its code
find each other.

## State (section 4.1)

::: unseenet.client.localapi.api.state
    options:
      show_root_heading: false
      heading_level: 3
      show_if_no_docstring: true

## Unlocking and setting up (section 4.2)

::: unseenet.client.localapi.api.setup
    options:
      show_root_heading: false
      heading_level: 3
      show_if_no_docstring: true

## Groups (section 4.3)

::: unseenet.client.localapi.api.groups
    options:
      show_root_heading: false
      heading_level: 3
      show_if_no_docstring: true

## Writing (sections 4.4, 4.5)

::: unseenet.client.localapi.api.writing
    options:
      show_root_heading: false
      heading_level: 3
      show_if_no_docstring: true

## People and safety (section 4.6)

::: unseenet.client.localapi.api.people
    options:
      show_root_heading: false
      heading_level: 3
      show_if_no_docstring: true

## Groups you run (section 4.7)

::: unseenet.client.localapi.api.running
    options:
      show_root_heading: false
      heading_level: 3
      show_if_no_docstring: true

## Who you are (section 4.8)

::: unseenet.client.localapi.api.identity
    options:
      show_root_heading: false
      heading_level: 3
      show_if_no_docstring: true

## Articles from a program (section 4.9)

::: unseenet.client.localapi.api.articles
    options:
      show_root_heading: false
      heading_level: 3
      show_if_no_docstring: true

## Events (section 5)

::: unseenet.client.localapi.api.events
    options:
      show_root_heading: false
      heading_level: 3
      show_if_no_docstring: true
