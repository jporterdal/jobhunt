## ADDED Requirements

### Requirement: Skill summary on the posting page
A posting's detail page SHALL show a skill summary across the full width of the page, between the posting's header and its description and triage panels. It SHALL show the posting's match score (see "Posting match score"), then two lists:
- **Have**: the posting skills whose credit (see "Skill credit") is above 0. Each SHALL show the posting skill's name, the profile skill its credit comes from, that link's relation and the profile skill's level. The profile skill SHALL be the one giving the highest credit; on a tie, the first in the order of the credit's links. Its name SHALL link to that skill on the profile page. When the profile skill has the same identity as the posting skill, the name SHALL be shown once, as that link.
- **Don't have**: every other posting skill, each with one reason:
  - `missing`, when it has a link but every profile skill it could take credit from is at `missing`; the linked profile skill SHALL be named, as a link to it on the profile page;
  - `not judged yet`, when it has no link, no override and no succeeded link judgment;
  - `no link` otherwise (judged without a usable relation, or the user's "no link" override).

Every posting skill (see "Skills a posting has" in `skill-linking`) SHALL appear in exactly one list. Each list SHALL be split into required and preferred, plus "importance not set" for marks without an importance; empty groups SHALL be left out. Have SHALL be ordered by credit, highest first, then by name; Don't have by name. Skills from the user's marks SHALL be styled as user-authored, and skills from model suggestions as model-derived.

When the posting has no skills, the summary SHALL say so and show no score. When the profile has no skills, the summary SHALL say so, with a link to the profile page.

The summary SHALL be computed from stored data without model requests. When the user changes the posting's skills or a skill's level from the posting page (accepting or rejecting a suggestion, undoing a rejection, changing a mark's importance or level, removing a mark), the summary SHALL be refreshed along with the panel that changed, without reloading the page. When a model run of the posting finishes while the page is open, the summary SHALL be refreshed with the model output.

#### Scenario: Have and don't have
- **WHEN** a posting asks for `Python` (required, profile `Python` at `proficient`), `AWS` (required, judged with no link) and `Docker` (preferred, linked `general` to `Containers` at `expert`)
- **THEN** the summary shows 46%; Have lists `Python` (same, proficient) under required and `Docker` → `Containers` (general, expert) under preferred; Don't have lists `AWS` (no link) under required

#### Scenario: Credit from a weaker link
- **WHEN** the latest judgment for `LoRA` relates `LLM fine-tuning` (at `missing`) as `general` and `Large language models` (at `proficient`) as `related`
- **THEN** Have lists `LoRA` → `Large language models` (related, proficient), and `Large language models` links to that skill on the profile page

#### Scenario: Linked to a missing skill
- **WHEN** a posting asks for `Kubernetes` and the profile has `Kubernetes` at `missing`
- **THEN** Don't have lists `Kubernetes` as `missing`, with a link to `Kubernetes` on the profile page

#### Scenario: Not judged yet
- **WHEN** the user marks `Terraform`, which no profile skill shares an identity with, and no link judgment for it has succeeded yet
- **THEN** Don't have lists `Terraform` as `not judged yet`; once a judgment finds no relation, it is listed as `no link`

#### Scenario: Marks and suggestions told apart
- **WHEN** Have lists `Python` from the user's mark and `Docker` from an unaccepted suggestion
- **THEN** `Python` is styled as user-authored and `Docker` as model-derived

#### Scenario: Refreshed after rejecting
- **WHEN** the user rejects the suggestion `Docker` in "Model says"
- **THEN** without a page reload, `Docker` is no longer in the summary and the score no longer counts it

#### Scenario: Refreshed after a level change
- **WHEN** the user sets `AWS` to `familiar` in "Skills asked for"
- **THEN** without a page reload, Have lists `AWS` (same, familiar) and the score rises

#### Scenario: Posting without skills
- **WHEN** a posting has no marks and no app run with suggestions
- **THEN** the summary says it has no skills yet and shows no score
