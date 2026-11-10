# Submission Guidance

Use this guidance before generating any outbound request file from a source list such as SELPA.

Official StudentTracker references:
- Submitting Files overview: https://help.studentclearinghouse.org/sths/article-categories/submitting-files/
- Difference between graduates and request files: https://help.studentclearinghouse.org/sths/knowledge-base/the-difference-between-a-graduates-file-and-a-request-file/

Clearinghouse guidance on file type:
- Graduates file: annual submission for all recent high school graduates; the Clearinghouse stores this data and uses it to generate StudentTracker reports.
- Request file: custom-cohort submission for ad hoc groups, including non-graduate students; it can be submitted at any time and is not stored by the Clearinghouse.

For SELPA specifically, do not assume the source is request-ready. If any mandatory StudentTracker fields are missing and cannot be derived from local reference data, that is a stopper and the file should not be generated until the gap is resolved.

Mandatory SELPA checks before use:
- Student first name
- Student last name
- Date of birth
- Last date of attendance or equivalent exit/last-attendance date
- ACT code for the last school attended or graduated from
- Account code and account name from the account reference sheet

## Header Row

The header row must be the first row in the file.

| Column | Description | Required | Format |
| --- | --- | --- | --- |
| A | Enter `H3` | Yes | 2 characters |
| B | Your account code, found on your account reference sheet | Yes | Up to 10 characters |
| C | Leave blank | No | Blank |
| D | Your account name, found on your account reference sheet | Yes | Up to 80 characters |
| E | File transmission date, the date you are sending the file | Yes | `YYYYMMDD` |
| F | Enter `SE` | Yes | 2 characters |
| G | Enter `D` | Yes | 1 character |

## Student Detail Rows

Enter each student's information in its own row starting at row 2.

| Column | Description | Required | Format |
| --- | --- | --- | --- |
| A | Enter `D3` | Yes | 2 characters |
| B | Leave blank | No | Blank |
| C | First name | Yes | Up to 40 characters |
| D | Middle name or initial | No | Up to 40 characters, no periods |
| E | Last name | Yes | Up to 40 characters |
| F | Suffix | No | Up to 3 characters, letters only, no numbers or punctuation |
| G | Date of birth | Yes | `YYYYMMDD` |
| H | Last date of attendance | Yes | `YYYYMMDD` |
| I | ACT code for the high school from which the student graduated or last attended, found on your account reference sheet | Yes | 6 characters |
| J | Leave blank | No | Blank |
| K | Requester return field for internal tracking. You can enter any additional ID or tag associated with the student here. | No | Up to 15 characters |
| L | Student ID assigned by the school or district | No | Up to 15 characters |
| M | Gender | No | 1 character |
| N | Ethnicity | No | 2 characters |
| O | Economically disadvantaged indicator, as dictated by the district or state | No | 1 character |
| P | 8th grade state assessment result, math | No | 1 character |
| Q | 8th grade state assessment result, ELA/reading | No | 1 character |
| R | High school assessment result, math | No | 1 character |
| S | High school assessment result, ELA/reading | No | 1 character |
| T | English learner or English as a second language indicator, as defined by the district or state | No | 1 character |
| U | Number of semesters of math completed, including non-traditional terms if credit was awarded | No | Up to 2 characters |
| V | Dual enrollment indicator | No | 1 character |
| W | Disability code | No | 1 character |
| X | Program code. Requester return field for internal tracking of a specific school, district, or state program | No | Up to 50 characters |
| Y | Enter `ED` for all student records | Yes | 2 characters |

### Valid Codes

`M` Gender:
- `M`: Male
- `F`: Female

`N` Ethnicity:
- `AM`: American Indian or Native Alaskan
- `AS`: Asian
- `BL`: Black or African American
- `HI`: Hispanic/Latino
- `PI`: Native Hawaiian or Pacific Islander
- `WH`: White
- `MU`: Two or more races

`O` Economically disadvantaged indicator:
- `Y`: Student is economically disadvantaged
- `N`: Student is not economically disadvantaged

`P`, `Q`, `R`, `S` Assessment results:
- `1`: Assessment result does not meet standards
- `2`: Assessment result is proficient or meets standards
- `3`: Assessment result is advanced or exceeds standards

`T` English learner or ESL indicator:
- `Y`: Student is an English learner or ESL student
- `N`: Student is not an English learner or ESL student

`V` Dual enrollment indicator:
- `Y`: Student is dual-enrolled
- `N`: Student is not dual-enrolled

`W` Disability code:
- `Y`: Student is considered disabled as defined by the state education authority
- `N`: Student is not considered disabled

## Trailer Row

The trailer row must be the last row in the spreadsheet.

| Column | Description | Required | Format |
| --- | --- | --- | --- |
| A | Enter `T3` | Yes | 2 characters |
| B | Enter the Excel row number for the trailer row | Yes | Up to 8 characters |
