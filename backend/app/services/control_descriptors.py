import re


async def element_descriptor(page, element) -> str:
    descriptor = await element.evaluate(
        r"""(el) => {
          const pieces = [];
          const GROUP_SELECTOR = 'fieldset,[role="radiogroup"],[role="group"]';
          const ARIA_WIDGET_SELECTOR = [
            '[role="button"]', '[role="checkbox"]', '[role="combobox"]',
            '[role="grid"]', '[role="link"]', '[role="listbox"]',
            '[role="menu"]', '[role="menubar"]', '[role="menuitem"]',
            '[role="menuitemcheckbox"]', '[role="menuitemradio"]', '[role="option"]',
            '[role="radio"]', '[role="radiogroup"]', '[role="scrollbar"]',
            '[role="searchbox"]', '[role="slider"]', '[role="spinbutton"]',
            '[role="switch"]', '[role="tab"]', '[role="tablist"]',
            '[role="textbox"]', '[role="toolbar"]', '[role="tree"]',
            '[role="treegrid"]', '[role="treeitem"]'
          ].join(',');
          const EDITABLE_SELECTOR = '[contenteditable]:not([contenteditable="false"])';
          const INTERACTIVE_SELECTOR =
            `input,select,textarea,button,${EDITABLE_SELECTOR},${ARIA_WIDGET_SELECTOR}`;
          const OWNERSHIP_CONTROL_SELECTOR =
            `input:not([type="hidden"]),select,textarea,button,${EDITABLE_SELECTOR},${ARIA_WIDGET_SELECTOR}`;
          const OPAQUE_CARD_RE = /^cards\[[^\]]+\]\[field\d+\]$/i;
          const push = (value) => {
            const clean = String(value || '').replace(/\s+/g, ' ').trim();
            if (clean && !pieces.includes(clean)) pieces.push(clean);
          };
          const cleanText = (value) => String(value || '').replace(/\s+/g, ' ').trim();
          const controlName = (control) => cleanText(control?.getAttribute?.('name'));
          const choiceKind = (control) => {
            if (!control) return '';
            const role = cleanText(control.getAttribute?.('role')).toLowerCase();
            if (role === 'radio' || role === 'checkbox') return role;
            if (control.matches?.('input[type="radio"]')) return 'radio';
            if (control.matches?.('input[type="checkbox"]')) return 'checkbox';
            return '';
          };
          const isChoiceControl = (control) => Boolean(choiceKind(control));
          const isGroupSubject = Boolean(el.matches?.(GROUP_SELECTOR));
          const usefulPrompt = (value) => {
            const text = cleanText(value);
            if (!text || text.length < 6 || text.length > 500) return '';
            if (!/[A-Za-z]/.test(text)) return '';
            if (/^(?:yes|no|true|false|type your response|write here)$/i.test(text)) return '';
            return text;
          };
          const containsInteractive = (node) => Boolean(
            node && (
              (node.matches && node.matches(INTERACTIVE_SELECTOR)) ||
              (node.querySelector && node.querySelector(INTERACTIVE_SELECTOR))
            )
          );
          const labelControlsInteractive = (label) => Boolean(
            label?.matches?.('label') && label.control &&
            label.control.matches?.(INTERACTIVE_SELECTOR)
          );
          const containsOwnedInteractiveLabel = (node) => {
            if (!node) return false;
            if (labelControlsInteractive(node)) return true;
            return Array.from(node.querySelectorAll?.('label') || [])
              .some((label) => labelControlsInteractive(label));
          };
          const genericHeading = (value) => {
            const text = cleanText(value).replace(/[:：]$/, '').trim();
            return /^(?:(?:additional|optional|custom|screening|pre[- ]?screening|job|candidate|applicant|cs)\s+)?(?:application\s+)?questions?$|^(?:additional\s+)?(?:application|applicant)\s+information$/i.test(text);
          };
          const promptSemanticHint = (node) => {
            if (!node) return false;
            const hint = [
              node.getAttribute?.('class'),
              node.getAttribute?.('id'),
              node.getAttribute?.('data-qa'),
              node.getAttribute?.('data-testid'),
            ].filter(Boolean).join(' ');
            return /(?:^|[-_\s])(?:prompt|question[-_\s]?(?:label|text|title)|field[-_\s]?label|application[-_\s]?label)(?:$|[-_\s])/i.test(hint);
          };
          const looksLikeUnstructuredPrompt = (node, value) => {
            const text = usefulPrompt(value);
            if (!text || genericHeading(text)) return '';
            if (promptSemanticHint(node)) return text;
            if (text.includes('?')) return text;
            if (/^(?:please\b|describe\b|tell\s+us\b|share\b|provide\b|explain\b|indicate\b|state\b|specify\b|desired\b|expected\b|target\b|preferred\b|salary\b|compensation\b|years?\s+of\b|work\s+authorization\b|current\s+company\b|current\s+location\b)/i.test(text)) {
              return text;
            }
            return '';
          };
          const promptResult = (candidates) => {
            const unique = [];
            for (const candidate of candidates || []) {
              const text = cleanText(candidate);
              if (text && !unique.includes(text)) unique.push(text);
            }
            return {
              text: unique.length === 1 ? unique[0] : '',
              ambiguous: unique.length > 1,
            };
          };
          const structuredPrompt = (node) => {
            if (!node) return promptResult([]);
            const selector =
              'label,legend,.application-label,[class*="question-label"],' +
              '[class*="field-label"],[class*="prompt"],[data-qa*="label"],[data-testid*="label"]';
            const candidates = [];
            for (const child of Array.from(node.children || [])) {
              if (!child.matches?.(selector)) continue;
              if (containsInteractive(child) || containsOwnedInteractiveLabel(child)) continue;
              const text = usefulPrompt(child.innerText);
              if (text && !genericHeading(text)) candidates.push(text);
            }
            return promptResult(candidates);
          };
          const unstructuredPrompt = (node, subject) => {
            const candidates = [];
            for (const child of Array.from(node?.children || [])) {
              if (child.contains(subject) || containsInteractive(child) ||
                  containsOwnedInteractiveLabel(child)) continue;
              const text = looksLikeUnstructuredPrompt(child, child.innerText);
              if (text) candidates.push(text);
            }
            return promptResult(candidates);
          };
          const structuralBoundary = (node) => {
            if (!node) return true;
            if (node.matches?.('section,form')) return true;
            const hint = [node.getAttribute?.('class'), node.getAttribute?.('id')]
              .filter(Boolean).join(' ');
            return /(?:^|[-_\s])(?:questions|questionnaire)(?:$|[-_\s])/i.test(hint);
          };

          // Establish opaque identity before reading ancestor/group semantics. Every group
          // subject is validated, even when the group itself carries the opaque name. A
          // group owns one opaque field only when every non-hidden interactive descendant
          // is the same-name, same-kind radio/checkbox choice. Any foreign native field,
          // editable surface, ARIA widget, repeated non-choice field, mixed choice kind,
          // or second opaque name makes the group compound and therefore fail closed.
          let opaqueName = cleanText(el.getAttribute?.('name'));
          if (!OPAQUE_CARD_RE.test(opaqueName)) opaqueName = '';
          let derivedChoiceKind = choiceKind(el);
          let unsafeOpaqueGroup = false;
          if (isGroupSubject) {
            const groupFields = Array.from(el.querySelectorAll(OWNERSHIP_CONTROL_SELECTOR));
            const candidateNames = new Set(
              groupFields
                .map((control) => controlName(control))
                .filter((name) => OPAQUE_CARD_RE.test(name))
            );
            if (opaqueName) candidateNames.add(opaqueName);
            if (candidateNames.size > 0) {
              const candidate = candidateNames.size === 1 ? Array.from(candidateNames)[0] : '';
              const kinds = new Set(groupFields.map((control) => choiceKind(control)).filter(Boolean));
              const ownsOneChoiceField = Boolean(candidate) && kinds.size === 1 &&
                groupFields.length > 0 &&
                groupFields.every((control) =>
                  isChoiceControl(control) && controlName(control) === candidate
                );
              if (ownsOneChoiceField) {
                opaqueName = candidate;
                derivedChoiceKind = Array.from(kinds)[0];
              } else {
                unsafeOpaqueGroup = true;
              }
            }
          }

          const ownsOpaqueField = (node) => {
            if (!opaqueName || !node) return false;
            const fields = [];
            if (node.matches?.(OWNERSHIP_CONTROL_SELECTOR)) fields.push(node);
            fields.push(...Array.from(node.querySelectorAll?.(OWNERSHIP_CONTROL_SELECTOR) || []));
            return !fields.some((control) => {
              if (control === el) return false;
              // The target's own structural group may be visible from a wider ancestor;
              // it is not a foreign field, but any sibling/nested group remains a boundary.
              if (control.matches?.(GROUP_SELECTOR) && control.contains?.(el)) return false;
              const kind = choiceKind(control);
              const sameChoice = Boolean(derivedChoiceKind) &&
                kind === derivedChoiceKind &&
                controlName(control) === opaqueName;
              return !sameChoice;
            });
          };

          // Direct control attributes are explicit ownership evidence. For a compound
          // opaque group, suppress group-level metadata entirely so it fails closed.
          if (!unsafeOpaqueGroup) {
            ['name','id','placeholder','aria-label','autocomplete',
             'data-testid','data-qa','data-automation-id'].forEach(
              (name) => push(el.getAttribute(name))
            );
            if (el.labels) Array.from(el.labels).forEach((label) => push(label.innerText));
            (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean)
              .forEach((id) => push(document.getElementById(id)?.innerText));
            (el.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean)
              .forEach((id) => push(document.getElementById(id)?.innerText));
          }
          if (opaqueName && isGroupSubject) push(opaqueName);

          // Preserve the established per-question wrapper path, but opaque controls may
          // use it only after proving that the wrapper owns no foreign field. If multiple
          // prompt candidates survive the ownership filters, do not choose among them.
          const applicationQuestion = el.closest(
            '.application-question,[data-qa="application-question"],[data-testid="application-question"]'
          );
          if (applicationQuestion && !unsafeOpaqueGroup &&
              (!opaqueName || ownsOpaqueField(applicationQuestion))) {
            let prompt = structuredPrompt(applicationQuestion);
            if (!prompt.text && !prompt.ambiguous) {
              prompt = unstructuredPrompt(applicationQuestion, el);
            }
            if (!prompt.ambiguous) push(prompt.text);
          }

          // Group labels are trustworthy for ordinary controls. For opaque Lever fields,
          // require single-field ownership before admitting aria-label or legend text.
          const group = el.closest(GROUP_SELECTOR);
          if (group && !unsafeOpaqueGroup && (!opaqueName || ownsOpaqueField(group))) {
            push(group.getAttribute('aria-label'));
            push(group.querySelector(':scope > legend')?.innerText);
          }
          if (!unsafeOpaqueGroup) push(el.closest('label')?.innerText);

          // Current Lever controls can expose only cards[uuid][fieldN] while the employer
          // prompt lives nearby. Every ancestor must prove field ownership before any
          // prompt is inspected. Structural section/form/questionnaire containers stop the
          // climb. Ambiguous local prompt evidence also stops the climb rather than letting
          // a farther ancestor silently decide which employer question owns the field.
          if (opaqueName) {
            let node = isGroupSubject ? el : el.parentElement;
            for (let depth = 0; node && depth < 6; depth += 1, node = node.parentElement) {
              if (!ownsOpaqueField(node)) break;
              if (structuralBoundary(node)) break;

              const structured = structuredPrompt(node);
              if (structured.ambiguous) break;
              if (structured.text) {
                push(structured.text);
                break;
              }

              const unstructured = unstructuredPrompt(node, el);
              if (unstructured.ambiguous) break;
              if (unstructured.text) {
                push(unstructured.text);
                break;
              }
            }
          }

          return pieces.join(' | ');
        }"""
    )
    return re.sub(r"\s+", " ", descriptor or "").strip()
