## MODIFIED Requirements

### Requirement: Documents
The user SHALL be able to upload documents and give each one a kind (`cv`, `cover_letter` or `other`) and a label. The system SHALL keep its own copy of every uploaded file, identified by content hash. Uploading identical bytes again SHALL reuse the stored file. The original filename, media type, size and upload time SHALL be recorded. Downloading a document SHALL return bytes identical to the upload. For PDF, DOCX, ODT, plain-text and markdown files, the system SHALL extract and store the document's text. For ODT files, each paragraph, heading, list item and table-cell paragraph SHALL become its own line in document order, and tab stops SHALL be kept as tab characters. Images, tracked-change records and comments SHALL NOT contribute text. Other file types SHALL be stored without text, and so SHALL files whose text cannot be extracted, with the reason noted. In both cases the upload SHALL still succeed.

#### Scenario: Uploading a CV
- **WHEN** the user uploads `cv-2026-10.pdf` as kind `cv` with label "CV v3"
- **THEN** the document is listed with its label, kind, filename and size, its extracted text can be viewed, and downloading it returns the identical file

#### Scenario: Same file twice
- **WHEN** the user uploads the same bytes under another label
- **THEN** a second document record exists, but only one stored copy of the file

#### Scenario: Unsupported type
- **WHEN** the user uploads a `.png`
- **THEN** the document is stored and downloadable, and it is marked as having no extracted text

#### Scenario: ODT with tab-aligned dates
- **WHEN** the user uploads an ODT file whose list item reads "MSc Statistics, Example Institute", then a tab stop, then "2009", and which has a contact table and a photo
- **THEN** the extracted text has that item on its own line with a tab character before "2009", each table cell's paragraphs on their own lines, and nothing from the photo
