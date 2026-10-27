"""Every style of an exported CV (design D7): fonts, sizes, spacing, margins, the right tab stop for dates and the
bullet list. odt.py uses only the names below and sets no properties of its own, so copying another CV's look
means replacing STYLES_XML and keeping these names.
"""

from __future__ import annotations

NAME = "CvName"
HEADLINE = "CvHeadline"
PRODUCED = "CvProduced"
CONTACT = "CvContact"
HEADING = "CvHeading"
PARAGRAPH = "CvParagraph"  # goal statements and summaries
BULLET = "CvBullet"  # a highlight's paragraph, inside the CvBullets list
BULLETS = "CvBullets"  # list style
ENTRY = "CvEntry"  # title and subtitle, a tab, the dates at the right margin
ENTRY_TITLE = "CvEntryTitle"  # text style for the title within CvEntry
LINE = "CvLine"
NOTE = "CvNote"
SOURCE = "CvSource"
SUB_ENTRY = "CvSubEntry"  # a record printed under another
SUB_LINE = "CvSubLine"  # its lines, sources and note

PARAGRAPH_STYLES = (NAME, HEADLINE, PRODUCED, CONTACT, HEADING, PARAGRAPH, BULLET, ENTRY, LINE, NOTE, SOURCE,
                    SUB_ENTRY, SUB_LINE)
TEXT_STYLES = (ENTRY_TITLE,)
LIST_STYLES = (BULLETS,)

# US Letter with 0.75in margins: the text is 7in wide, which is where the dates' tab stop sits.
STYLES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
    xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
    office:version="1.3">
  <office:font-face-decls>
    <style:font-face style:name="Liberation Sans" svg:font-family="'Liberation Sans'" style:font-family-generic="swiss" style:font-pitch="variable"/>
  </office:font-face-decls>
  <office:styles>
    <style:default-style style:family="paragraph">
      <style:paragraph-properties fo:margin-top="0in" fo:margin-bottom="0in" fo:line-height="115%"/>
      <style:text-properties style:font-name="Liberation Sans" fo:font-size="10pt" fo:language="en" fo:country="CA"/>
    </style:default-style>
    <style:style style:name="Standard" style:family="paragraph" style:class="text"/>
    <style:style style:name="CvName" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:text-align="center"/>
      <style:text-properties fo:font-size="20pt" fo:font-weight="bold"/>
    </style:style>
    <style:style style:name="CvHeadline" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:text-align="center" fo:margin-top="0.03in"/>
      <style:text-properties fo:font-size="12pt"/>
    </style:style>
    <style:style style:name="CvProduced" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:text-align="center" fo:margin-top="0.03in"/>
      <style:text-properties fo:font-size="9pt" fo:color="#555555"/>
    </style:style>
    <style:style style:name="CvContact" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:text-align="center" fo:margin-top="0.03in" fo:margin-bottom="0.08in"/>
      <style:text-properties fo:font-size="9pt"/>
    </style:style>
    <style:style style:name="CvHeading" style:family="paragraph" style:parent-style-name="Standard" style:default-outline-level="1" style:class="text">
      <style:paragraph-properties fo:margin-top="0.16in" fo:margin-bottom="0.06in" fo:keep-with-next="always"
          fo:border-bottom="0.5pt solid #000000" fo:padding-bottom="0.02in"/>
      <style:text-properties fo:font-size="12pt" fo:font-weight="bold"/>
    </style:style>
    <style:style style:name="CvParagraph" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-bottom="0.05in" fo:text-align="justify"/>
    </style:style>
    <style:style style:name="CvBullet" style:family="paragraph" style:parent-style-name="Standard" style:list-style-name="CvBullets">
      <style:paragraph-properties fo:margin-bottom="0.03in"/>
    </style:style>
    <style:style style:name="CvEntry" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-top="0.06in" fo:keep-with-next="always">
        <style:tab-stops>
          <style:tab-stop style:position="7in" style:type="right"/>
        </style:tab-stops>
      </style:paragraph-properties>
      <style:text-properties fo:font-size="10.5pt"/>
    </style:style>
    <style:style style:name="CvEntryTitle" style:family="text">
      <style:text-properties fo:font-weight="bold"/>
    </style:style>
    <style:style style:name="CvLine" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-left="0.2in"/>
    </style:style>
    <style:style style:name="CvNote" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-left="0.2in"/>
      <style:text-properties fo:font-style="italic" fo:color="#444444"/>
    </style:style>
    <style:style style:name="CvSource" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-left="0.2in"/>
      <style:text-properties fo:font-size="9pt" fo:color="#333333"/>
    </style:style>
    <style:style style:name="CvSubEntry" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-left="0.2in" fo:margin-top="0.03in" fo:keep-with-next="always">
        <style:tab-stops>
          <style:tab-stop style:position="6.8in" style:type="right"/>
        </style:tab-stops>
      </style:paragraph-properties>
    </style:style>
    <style:style style:name="CvSubLine" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-left="0.4in"/>
    </style:style>
    <text:list-style style:name="CvBullets">
      <text:list-level-style-bullet text:level="1" text:bullet-char="•">
        <style:list-level-properties text:list-level-position-and-space-mode="label-alignment">
          <style:list-level-label-alignment text:label-followed-by="listtab" text:list-tab-stop-position="0.25in"
              fo:text-indent="-0.18in" fo:margin-left="0.25in"/>
        </style:list-level-properties>
      </text:list-level-style-bullet>
    </text:list-style>
  </office:styles>
  <office:automatic-styles>
    <style:page-layout style:name="CvPage">
      <style:page-layout-properties fo:page-width="8.5in" fo:page-height="11in" style:print-orientation="portrait"
          fo:margin-top="0.75in" fo:margin-bottom="0.75in" fo:margin-left="0.75in" fo:margin-right="0.75in"/>
    </style:page-layout>
  </office:automatic-styles>
  <office:master-styles>
    <style:master-page style:name="Standard" style:page-layout-name="CvPage"/>
  </office:master-styles>
</office:document-styles>
"""
