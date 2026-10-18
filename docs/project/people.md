# People

Who is behind Unseenet: who created it, who develops and maintains it,
the team, the contributors and the developers, and who does what. Anyone
who joins the project adds themselves here by pull request.

Two of the names below are not people: an AI assistant and GitHub's
automation. They are listed because their work shows up everywhere -
commits, release notes, posts in the project's groups - and you should
know who (or what) made it.

## People

| Name | Role | Where to find them |
|------|------|--------------------|
| **Andreas Lorensen** | Started the project and maintains it: the protocol, the node, the clients, the project's nodes and keys. Approves UN-RFCs and pull requests. | GitHub [@andlo](https://github.com/andlo); on Unseenet in `unseenet` and `unseenet.help` |

For now, that is everybody. If you would like to help - run a node, write
a client, review a UN-RFC, improve the docs - say so in `unseenet` or open
an issue.

## Not people

| Name | What it is | What it does |
|------|-----------|--------------|
| **Claude** | An AI assistant made by Anthropic, working for Andreas | Writes code, specs and docs with him; merges pull requests, tags releases and writes release notes when he asks. Commits and texts it wrote are reviewed by Andreas. It is not a member of the project in its own right and does not speak for it. |
| **GitHub Actions** | GitHub's automation | Runs the tests and builds the portable and bootable releases. With the GitHub poster key (see [The project's keys](keys.md)) it posts releases to `unseenet.announce`, the node list to `unseenet.nodes`, the root and hierarchy lists, and the daily canaries. |

## Bots on Unseenet

Bots have their own keys and say that they are bots in their profile
(UN-RFC 0022).

| Bot | Where | What |
|-----|-------|------|
| **Unseenet help (bot)** | `unseenet.help` | Answers questions from the documentation, issues and pull requests when nobody has after a while, or right away when named `@helpbot`. It cites its sources and can be wrong. Code: [unseenet-helpbot](https://github.com/unseenet/unseenet-helpbot). |
| **The news bots** | `alt.news.*`, `alt.history.onthisday`, `alt.privacy.eff`, `alt.space.nasa` | Post current content from open sources, credited in each post. Code: [unseenet-bots](https://github.com/unseenet/unseenet-bots). |
