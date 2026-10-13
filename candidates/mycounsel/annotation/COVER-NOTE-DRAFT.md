# Cover note for the annotator (draft for Sebastian's review, not sent)

Subject: Blind annotation of a synthetic ICT services agreement, about two hours

Dear [name],

thank you for agreeing to help. Attached is a small annotation pack for a
synthetic exercise. Nothing in it concerns a real party, service or matter, and
nothing you write will be treated as legal advice.

**What I am asking for.** The pack contains one fictional English-language ICT
services agreement under German law in three variants, and two short review
playbooks: six commercial points and six points taken from Article 30 of
Regulation (EU) 2022/2554 (DORA). For each variant and each playbook, please
record which playbook points a careful reviewer acting for the customer would
have to raise, and where. That makes six short templates. `GUIDELINE.md` in the
pack explains the unit of annotation and shows the format.

**Why blind.** Your answers become the reference against which automated
contract-review output is later compared. They are only useful if they are your
own reading. Please do not search for the agreement online, and please tell me
in the template if you have already seen automated findings for it. I will
annotate the same material separately. Where our answers differ, we resolve each
difference in writing, and your reading is recorded as the independent one.

**What I am not asking for.** No severity ratings, no redrafting and no view on
whether the playbooks are complete. The DORA playbook is a deliberately narrow
selection from Article 30 and is not a compliance checklist. If you think a
playbook point is wrongly framed, the `uncertainties` field is the place to say
so.

**Practicalities.**

- Please return the six filled templates and a note of the time you spent by
  [date].
- The pack lists every file with a hash in `MANIFEST.json`, so we can both
  confirm we worked from the same material.
- I would like to name you as the independent annotator in the project record
  and, if the work is published, in its acknowledgements. Please tell me whether
  you agree and how you would like to be described. Without your agreement your
  contribution stays unnamed.
- The templates you return are kept with the experiment record and may be
  published with it. Please write the label "[label]" in the `annotator` field,
  not your name.

Thank you, and do call if anything in the guideline is unclear.

Sebastian

---

Notes for Sebastian before sending:

- Complete the legal review of the playbooks and the source register first. The
  guideline, the register and the manifest are hashed into every template; an
  edit after sending makes the returned annotations unusable.
- Attach `candidates/mycounsel/annotation-bundle/mycounsel-annotation-pack.zip`.
  After any change to the guideline, the playbooks, the documents or the source
  register, rebuild in this order: `python candidates/mycounsel/build_fixtures.py`
  (playbooks and documents are written there), `make candidate-pack`,
  `make candidate-bundle`. The last command prints the archive's SHA-256.
- Annotators write a label, not a name (your decision of 13 October 2026).
  Agree the label with the annotator and replace "[label]" above. Use a label
  of your own for your six templates. Check the `annotator` field of every
  returned file before it is committed.
- Record the annotator's name, the date sent, the archive hash and the remit in a
  dated note. That note is what `reviewerEvidence` later points to.
- Fill your own six templates before you open the annotator's return, in a copy
  outside `annotation-pack/`.
