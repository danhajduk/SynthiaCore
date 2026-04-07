# Feature Request: Probation Grants And Provider Grant Update APIs

Status: Not developed
Requested: 2026-04-07

## Summary

Add a probation-based grant lifecycle for newly granted or abusive nodes, plus explicit service/provider-node APIs for grant updates.

This request introduces three connected capabilities:

1. first grant request is issued as a probation grant
2. abusive nodes with trusted grants are downgraded back into probation
3. service/provider nodes must expose APIs for grant updates

## Requested Behavior

### 1. First Grant Request Is A Probation Grant

The first grant issued to a client for delegated execution should be a probation grant rather than a fully trusted long-lived grant.

Requested probation rules:

- probation grant duration is one week
- both client node and provider/service node must report usage at least once per day
- daily reporting is required even when usage is zero
- if Core does not receive required daily reports for two consecutive days, the probation grant is revoked
- Core must compare client-reported and provider-reported usage and verify that client reports are true within reasonable tolerance before promotion
- probation may not continue for more than three weeks total
- if a node remains on probation for more than three weeks, the node is downgraded to a restricted daily grant model

### 2. Abusive Trusted Nodes Re-Enter Probation

If a node with a previously trusted grant becomes abusive, the node should be downgraded back to probation and restart the probation cycle.

Examples of abusive behavior that this feature should eventually support as policy inputs:

- missing required daily reports
- materially inconsistent client and provider usage reports
- repeated overuse or policy violations
- suspicious reporting patterns

Requested downgrade rule:

- a trusted node that is marked abusive is downgraded to probation
- the node then re-enters the same probation lifecycle defined above

### 3. Service And Provider Nodes Must Expose Grant Update APIs

Service/provider nodes must expose APIs so Core and authorized nodes can observe grant lifecycle updates.

Minimum desired capability:

- provider/service nodes expose grant update endpoints or grant status endpoints
- provider/service nodes can surface current probation status, revocation status, and grant restrictions
- provider/service nodes can surface grant usage progress relevant to reconciliation

## Why This Is Needed

This request addresses the gap between:

- trusting a node enough to authorize it
- trusting the node enough to rely only on its usage reporting

The probation model creates a staged trust lifecycle:

- new nodes earn trusted grant status
- abusive nodes can be downgraded and re-validated
- provider-side reporting becomes part of the trust decision

## Desired Probation Lifecycle

```text
First delegated grant request
        |
        v
Issue 1-week probation grant
        |
        v
Daily reporting required from:
- client node
- provider/service node
        |
        +-----------------------------+
        |                             |
        v                             v
Reports present and                Reports missing for
reasonably consistent              2 consecutive days
        |                             |
        v                             v
Continue probation               Revoke probation grant
or promote if criteria met             |
        |                              v
        |                        Node must re-request
        v
Probation exceeds 3 weeks
        |
        v
Downgrade to restricted daily grant
```

## Promotion Requirements

Promotion from probation to full trusted grant should require all of the following:

- daily client reports are present
- daily provider/service reports are present
- client and provider totals reconcile within defined tolerance
- no major abuse or policy-violation signals are present

The exact tolerance policy is not implemented and should be defined during implementation.

## Restricted Daily Grant Follow-Up

If a node remains on probation for more than three weeks, it should not stay in indefinite probation.

Requested fallback:

- downgrade that node to restricted daily grants
- require daily re-evaluation and tighter reporting expectations

The exact restricted-daily-grant contract is not implemented yet and should be designed explicitly.

## Relationship To Existing Requests

This request builds on earlier identified gaps:

- client-only usage reporting is insufficient for reconciliation
- current grants have no staged trust model
- current trusted nodes are not automatically recycled into a stricter monitoring mode after abuse

Related tracked work:

- [feature-request-service-node-daily-budget-reporting.md](/home/dan/Projects/Hexe/docs/core/feature-request-service-node-daily-budget-reporting.md)
- [node-budget-assignment-flow.md](/home/dan/Projects/Hexe/docs/core/node-budget-assignment-flow.md)

## Suggested Acceptance Criteria

- first delegated grant issued to a new client is a probation grant
- probation grants last one week
- both client and provider/service nodes must report daily, including zero-usage days
- missing reporting for two consecutive days revokes the probation grant
- Core can compare client-side and provider-side usage reports before promotion
- probation cannot continue longer than three weeks
- nodes that exceed three weeks of probation are downgraded to restricted daily grants
- abusive trusted nodes can be downgraded back to probation automatically or by policy
- provider/service nodes expose APIs for grant updates and grant-status visibility
