# site-extra

Files copied as they are into the built site (unseenet.org) after mkdocs,
which leaves out folders starting with a dot.

- `.well-known/matrix/server` and `client`: Matrix delegation, so that
  `@gateway:unseenet.org` and other `:unseenet.org` users live on
  `matrix.unseenet.org` (the homeserver behind the Matrix gateway, UN-RFC 0037).
