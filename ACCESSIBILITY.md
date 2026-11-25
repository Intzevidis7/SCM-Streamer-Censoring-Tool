# Accessibility

## Commitment and scope

Bad Word Beep aims to make its Windows desktop interface and documentation easier to use. Accessibility is an ongoing effort, not a claim of compliance with a particular accessibility standard.

The project targets Windows desktop audio workflows, including OBS and virtual audio routing. Screen-reader compatibility, keyboard-only operation, high-contrast behavior, and display-scaling support have not been comprehensively audited.

## Known limitations and areas to test

- Device selection and routing may require additional assistance.
- Audio-only beep feedback may not be accessible to everyone. Activity logs can help explain detections but are not a guaranteed equivalent.
- Status text, colors, focus order, text scaling, and assistive-technology announcements need further testing.
- Recognition may behave differently across voices, accents, speech patterns, and recording conditions.

## Reporting a barrier

Open an issue with an Accessibility: title. Include app and Windows versions, assistive technology and version if applicable, relevant display scaling, reproduction steps, and expected behavior.

Do not share medical information or private recordings. Screenshots and short descriptions are sufficient when they explain the barrier. Suggestions are welcome; implementation depends on maintainer capacity.
