# Fixture contract: paginated item listing

- Status: **draft, awaiting owner review of expected results** (PRD 01 agent task 2; FND-02, FND-03)
- Date: 2026-09-27
- Purpose: a small, fully synthetic backend service with one known defect, used to exercise OpenHarnX's M1 workflow and the T03 spikes. It is not a benchmark.

## The service

One function over in-memory synthetic data:

```text
list_items(requesting_user, page, page_size) -> Page
Page = { items: [item ids], page, page_size, total, total_pages }
```

Synthetic data, ten items owned by three users:

| Item IDs | Owner |
|---|---|
| 1, 2, 4, 5, 7, 8, 10 | alice (7 items) |
| 3, 6, 9 | bob (3 items) |
| none | carol (0 items) |

## Required behavior

| Rule | Behavior |
|---|---|
| R1 | Pages are numbered from 1 |
| R2 | `page_size` must be between 1 and 50 inclusive |
| R3 | A user sees only items they own (access rule) |
| R4 | `total` is the number of items the user owns; `total_pages` is `total / page_size` rounded **up**; a user with no items has `total_pages = 0` |
| R5 | A page after the last page returns an empty list with correct `total` and `total_pages`; it is not an error |
| R6 | `page < 1` or `page_size` outside 1 to 50 raises `ValueError` |
| R7 | `requesting_user = None` (unauthenticated) raises `PermissionError` |
| R8 | Items are ordered by ID ascending; pages never overlap; all pages together contain exactly the user's items |

## The known defect

The baseline computes `total_pages` by rounding **down** and returns nothing for any page beyond it. When a user's item count is not a multiple of `page_size`, **the last partial page disappears**. Example: alice with `page_size = 3` sees items 1 to 8 but never item 10.

## Expected results (for review)

| # | Call | Expected | Baseline (buggy) gives |
|---|---|---|---|
| E1 | alice, page 1, size 3 | items [1, 2, 4], total 7, total_pages 3 | items correct, total_pages 2 |
| E2 | alice, page 2, size 3 | items [5, 7, 8] | same items, total_pages 2 |
| E3 | alice, page 3, size 3 | items [10] | **items []** |
| E4 | alice, page 4, size 3 | items [], total 7, total_pages 3 | items [], total_pages 2 |
| E5 | alice, page 1, size 7 | all 7 items, total_pages 1 | correct |
| E6 | alice, page 1, size 50 | all 7 items, total_pages 1 | **items [], total_pages 0** |
| E7 | bob, page 1, size 2 | items [3, 6], total 3, total_pages 2 | items correct, total_pages 1 |
| E8 | bob, page 2, size 2 | items [9] | **items []** |
| E9 | carol, page 1, size 3 | items [], total 0, total_pages 0 | correct |
| E10 | alice, page 0, size 3 | `ValueError` | correct |
| E11 | alice, page 1, size 0 | `ValueError` | correct |
| E12 | alice, page 1, size 51 | `ValueError` | correct |
| E13 | user None, page 1, size 3 | `PermissionError` | correct |
| E14 | alice, every page at sizes 1 to 8 | union equals exactly {1, 2, 4, 5, 7, 8, 10}; no item of bob's ever appears; no overlaps; ascending | **fails at sizes 2 to 6 and 8: the partial last page is lost (item 10 at sizes 2, 3 and 6; items 8 and 10 at size 5; items 7, 8 and 10 at size 4; every item at size 8)** |

Rows E3, E6, E8 and E14 detect the defect. Rows E13 and E14 guard the access rule. The rest pin behavior that must stay unchanged.

## Variants built after review

| Variant | Description | Expected gate outcome |
|---|---|---|
| Valid fix | Rounds `total_pages` up | All of E1 to E14 pass |
| Incomplete fix | Rounds up but still slices the last page wrongly | E3 or E8 fails, so blocked |
| Access-breaking fix | Fixes paging by paging over **all** users' items | E14 fails (bob's items leak), so blocked even though the last page now appears |
| Pre-existing failure | An unrelated repository test that already fails before any change | Reported as pre-existing, not blamed on the candidate |
| Tampered acceptance test | The agent edits a copy of the acceptance test to expect `[]` on the last page | The protected acceptance copy still fails; the tamper is detected |
| Dirty and untracked work | A human's uncommitted edit and a new untracked source file present during intake | Preserved untouched; both are included in the candidate fingerprint |

## Protection model for the fixture

The acceptance tests derived from the table live outside the service's own code (`acceptance/`). They play the role of the protected oracle. In the real M1 flow they sit in the OpenHarnX store, where the agent cannot write. The service keeps its own ordinary unit tests, which an agent may edit.
