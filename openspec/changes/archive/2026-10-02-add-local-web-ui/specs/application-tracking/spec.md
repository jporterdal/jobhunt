## Purpose

Tracks the user's job applications from first interest to outcome, including ones with no stored posting, along with the documents sent, the companies involved and the people contacted.

## ADDED Requirements

### Requirement: Applications from postings
The user SHALL be able to start an application from a posting's detail page. The application SHALL be linked to the posting's job ID, and its title, company and URL SHALL come from the posting. A posting SHALL have at most one application.

#### Scenario: Applying to a posting
- **WHEN** the user starts an application from job 9000000201
- **THEN** an application linked to that posting exists, and the posting's list row and detail page show its status

#### Scenario: Second application for the same posting
- **WHEN** the posting already has an application
- **THEN** the detail page links to that application and offers no new one

### Requirement: Applications without a stored posting
The user SHALL be able to create an application by hand, with a required job title and company and an optional URL. The user SHALL be able to link such an application to a posting later, as long as that posting has no application yet. Linking SHALL keep the application's events, documents and contacts.

#### Scenario: Manual application
- **WHEN** the user creates an application for "Data Engineer" at "Acme" with URL `https://acme.example/careers/42`
- **THEN** the application appears on the board, its URL is shown as a link, and it has no posting

#### Scenario: Linking later
- **WHEN** that job is later imported and the user links the application to the new posting
- **THEN** the application keeps its history and now also shows the posting and its original-posting link

### Requirement: Event history drives status
Each application SHALL have a dated history of events. Each event has a date (defaulting to today, changeable by the user), a kind and an optional note. The kinds are the statuses `interested`, `applied`, `screening`, `interviewing`, `offer`, `accepted`, `rejected`, `ghosted` and `withdrawn`, plus `note`. The application's status SHALL be the kind of its latest non-`note` event, by event date and then by entry order. Events SHALL NOT be edited in place. The user SHALL be able to delete a mistaken event, after which the status is recomputed.

#### Scenario: Progressing
- **WHEN** an application has `applied` on 2026-09-28 and `screening` on 2026-10-03
- **THEN** its status is `screening`

#### Scenario: Back-dated event
- **WHEN** the user then adds `interested` dated 2026-09-25
- **THEN** the status stays `screening` and the history lists the events in date order

#### Scenario: Deleting a mistake
- **WHEN** the user deletes the `screening` event
- **THEN** the status becomes `applied`

### Requirement: Next action and compensation notes
Each application SHALL have an optional next action, made of a short text and an optional due date, and optional free-text compensation notes. An open application whose next action is due today or earlier SHALL be highlighted as due.

#### Scenario: Overdue follow-up
- **WHEN** an application in status `applied` has the next action "Follow up with recruiter" due yesterday
- **THEN** the board and the application page highlight it as due

### Requirement: Applications board
The system SHALL show applications grouped by status. Open statuses SHALL come first, in pipeline order, followed by the closed statuses (`accepted`, `rejected`, `ghosted`, `withdrawn`), which SHALL be collapsible. Each card SHALL show the title, the company, the original or manual URL as a link, the latest event date and the next action. The board SHALL also list the open applications that have a next action, ordered by due date.

#### Scenario: Board grouping
- **WHEN** there are applications in `applied`, `interviewing` and `rejected`
- **THEN** the `applied` and `interviewing` columns come before the collapsed `rejected` group

### Requirement: Documents
The user SHALL be able to upload documents and give each one a kind (`cv`, `cover_letter` or `other`) and a label. The system SHALL keep its own copy of every uploaded file, identified by content hash. Uploading identical bytes again SHALL reuse the stored file. The original filename, media type, size and upload time SHALL be recorded. Downloading a document SHALL return bytes identical to the upload. For PDF, DOCX, plain-text and markdown files, the system SHALL extract and store the document's text. Other file types SHALL be stored without text, and so SHALL files whose text cannot be extracted, with the reason noted. In both cases the upload SHALL still succeed.

#### Scenario: Uploading a CV
- **WHEN** the user uploads `cv-2026-10.pdf` as kind `cv` with label "CV v3"
- **THEN** the document is listed with its label, kind, filename and size, its extracted text can be viewed, and downloading it returns the identical file

#### Scenario: Same file twice
- **WHEN** the user uploads the same bytes under another label
- **THEN** a second document record exists, but only one stored copy of the file

#### Scenario: Unsupported type
- **WHEN** the user uploads a `.png`
- **THEN** the document is stored and downloadable, and it is marked as having no extracted text

### Requirement: Documents linked to applications
The user SHALL be able to link any document to any number of applications and unlink it again. An application SHALL list its linked documents, and a document SHALL list the applications it is linked to.

#### Scenario: One CV, two applications
- **WHEN** "CV v3" is linked to the Example Advisory and Example Bank applications
- **THEN** both applications list "CV v3", and the document lists both applications

### Requirement: Companies
The system SHALL let the user keep a company record, matched case-insensitively to postings and applications by company name, with optional website URL, careers or listing URL, and notes. A company page SHALL list the matching postings, applications and contacts. The company name on a posting or application SHALL link to its company page and offer to create the record when none exists. URLs SHALL be shown as links.

#### Scenario: Company page
- **WHEN** the user creates a record for "Example Advisory" with a careers URL, and two stored postings name that company
- **THEN** the Example Advisory page shows the careers link and both postings with their original-posting links

### Requirement: Contacts
The user SHALL be able to record contacts with a name, zero or more email addresses, a role, an optional profile URL and notes. A contact can optionally belong to a company and can be linked to any number of applications. Email addresses SHALL be shown as `mailto:` links.

#### Scenario: Recruiter contact
- **WHEN** the user adds recruiter "Jane Doe" with email `jane@advisory.example` at Example Advisory and links her to the Example Advisory application
- **THEN** the application and the company page both show Jane Doe with a `mailto:jane@advisory.example` link

### Requirement: Application data is user-authored
Applications, events, documents, document links, companies and contacts SHALL be stored as user-authored data. Importing or re-importing postings SHALL leave them unchanged. Linked documents SHALL be stored only locally, in the database's managed document folder.

#### Scenario: Re-import with an application
- **WHEN** a posting with an application is re-captured
- **THEN** the application, its events and its linked documents are unchanged
