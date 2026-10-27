## MODIFIED Requirements

### Requirement: Requesting extraction
The posting detail page SHALL offer an action to queue extraction of the posting's latest snapshot with the selected model, segmentation method and skill extraction method. The posting list SHALL offer an action to queue extraction for every listed, non-dismissed posting that has no successful run for its latest snapshot with the current model and pipeline. Before the user confirms, the action SHALL state how many postings it will queue. Queuing a posting that already has a queued or running job SHALL NOT add a second job.

#### Scenario: Bulk extraction
- **WHEN** the list shows 28 postings, 3 dismissed and 5 already extracted with the current settings, and the user starts bulk extraction
- **THEN** the action says it will queue 20 postings and, once confirmed, queues 20 jobs

#### Scenario: Double request
- **WHEN** the user clicks extract twice on a posting whose job is still queued
- **THEN** only one job is queued for that posting

#### Scenario: Extraction with the chosen skill method
- **WHEN** the skill extraction method is set to `atomic@4` and the user extracts a posting
- **THEN** the stored run's pipeline id contains `skills=atomic@4`

### Requirement: Accepting and rejecting suggestions
For a run on the posting's latest snapshot, the user SHALL be able to accept a verified skill suggestion. Accepting SHALL create a skill mark with the suggestion's skill name, quote and importance, and an origin showing it came from a suggestion. Skill names SHALL be matched to existing skills case-insensitively. The user SHALL be able to accept all verified suggestions in one group (required or preferred) with one action. A suggestion whose skill the posting already marks SHALL be shown as already marked and SHALL NOT be accepted again.

The user SHALL be able to reject a suggestion, giving one of two reasons:
- **not a skill:** the suggestion is not a skill by the user's definition
- **not for me:** it is a skill, but not one the user wants marked

A rejected skill SHALL be hidden for that posting in every run, including later ones, until the user undoes the rejection. Shown rejected suggestions SHALL display their reason, or say that none was given for rejections made before reasons existed. The user SHALL be able to set or change the reason of a rejected suggestion without undoing it. The reason SHALL be stored with the rejection as user-authored data. Suggestions from runs on older snapshots SHALL NOT be acceptable.

#### Scenario: Accepting a required skill
- **WHEN** the user accepts the required suggestion `MLflow` quoting "MLflow for experiment tracking"
- **THEN** the posting has a skill mark for `MLflow` with that quote, importance required and origin suggestion, and the suggestion shows as already marked

#### Scenario: Rejection survives re-extraction
- **WHEN** the user rejects suggestion `Communication` on a posting and later extracts the posting again
- **THEN** the new run's `Communication` suggestion is hidden as rejected, and the user can show and undo it

#### Scenario: Rejecting with a reason
- **WHEN** the user rejects `Refactoring` as not a skill and `Cursor` as not for me
- **THEN** both are hidden as rejected, and when shown, `Refactoring` says "not a skill" and `Cursor` says "not for me"

#### Scenario: Reason added to an earlier rejection
- **WHEN** a suggestion `Ray` was rejected before reasons existed, and the user shows rejected suggestions and sets its reason to not for me
- **THEN** `Ray` stays rejected, and its reason is now not for me
