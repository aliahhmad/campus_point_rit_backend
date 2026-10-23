# Workflow walkthroughs

Follow these guides in order for a complete demo:

1. [Start the backend](quick-start.md) and import locations.
2. [Create accounts](usage/add-user.md), including a requester, contributor,
   and administrator.
3. [Create a request and hold its reward](development/requests.md).
4. [Browse the feed](development/request-feed.md) and
   [submit another user's answer](development/responses.md).
5. [Accept the answer](development/acceptance.md) and inspect the contributor's
   points and reputation.
6. [Observe expiry and conflicts](development/expiration.md).
7. [Resolve a conflict as administrator](development/conflict-resolution.md).
8. Read [2PC](development/two-phase-commit.md) and
   [recovery](development/recovery.md) to understand interrupted actions.

Use disposable data when exercising failures. The [workflow tests](development/testing.md)
cover simulated crashes and lost replies without requiring manual edits to
application balances or coordinator decisions.
