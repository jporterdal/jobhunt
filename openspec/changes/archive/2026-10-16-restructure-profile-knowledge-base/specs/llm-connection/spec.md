## MODIFIED Requirements

### Requirement: Background job queue
Model work SHALL be added to a queue stored in the database and processed one job at a time, outside the request, oldest first. A job SHALL be one of: extracting a posting, extracting a document, or judging links. Posting extraction SHALL be queued only when the user requests it. Document extraction SHALL be queued when the user requests it or uploads a CV (see "Adding a document to the profile"), and link judging when the user requests it or skills change (see "Re-judging when skills change"); a document extraction SHALL NOT queue link judging by itself, since it changes no profile skill. The interface SHALL show each queued job's subject (a posting, a document, or skill links) and state: queued, running, done, failed or cancelled. Failed jobs SHALL show their error. The user SHALL be able to cancel queued jobs. Cancelling a running job SHALL stop it before its next step. Nothing from a cancelled posting or document extraction SHALL be stored. A cancelled link-judging job SHALL keep the judgments it finished before stopping. Jobs that were running when `serve` stopped SHALL be queued again at the next start. While the server is unreachable, queued jobs SHALL wait rather than fail. Queue processing SHALL run only while `serve` runs, and SHALL do nothing except call the configured Ollama address and store results.

#### Scenario: Queue progress
- **WHEN** the user queues extraction for three postings
- **THEN** the interface shows one running and two queued, and updates each to done or failed without a page reload

#### Scenario: Restart with queued work
- **WHEN** `serve` stops while one job is running and two are queued, and is started again
- **THEN** all three jobs are queued and are processed

#### Scenario: Ollama goes offline mid-queue
- **WHEN** the server becomes unreachable while jobs are queued
- **THEN** the queued jobs stay queued and processing resumes when the server is reachable again

#### Scenario: Cancelling
- **WHEN** the user cancels the queue while two jobs are queued
- **THEN** both are marked cancelled and no model requests are made for them

#### Scenario: Mixed kinds in order
- **WHEN** a posting extraction is queued, then a CV is uploaded, which queues a document extraction, and once it finishes the user accepts one of its claim suggestions, which queues link judging
- **THEN** the jobs run in that order, and the queue shows a posting, a document and "skill links" as their subjects

#### Scenario: Document extraction alone
- **WHEN** a document extraction succeeds and the user accepts none of its suggestions
- **THEN** no link-judging job is queued

#### Scenario: Cancelling link judging midway
- **WHEN** the user cancels a running link-judging job after 40 of 120 posting skills were judged
- **THEN** the 40 judgments are kept and take effect, and the rest are judged by the next judging job
