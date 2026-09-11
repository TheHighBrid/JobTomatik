import re


async def element_descriptor(page, element) -> str:
    descriptor = await element.evaluate(
        r"""(el) => {
          const pieces = [];
          const GROUP_SELECTOR = 'fieldset,[role="radiogroup"],[role="group"]';
          const INTERACTIVE_SELECTOR =
            'input,select,textarea,button,[role="radio"],[role="checkbox"],[role="combobox"]';
          const FIELD_SELECTOR = 'input:not([type="hidden"]),select,textarea';
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
          const labelOwnsInteractive = (node) => Boolean(
            node?.matches?.('label') && node.control &&
            node.control.matches?.(INTERACTIVE_SELECTOR)
          );
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
          const structuredPrompt = (node) => {
            if (!node) return '';
            const selector =
              'label,legend,.application-label,[class*="question-label"],' +
              '[class*="field-label"],[class*="prompt"],[data-qa*="label"],[data-testid*="label"]';
            for (const child of Array.from(node.children || [])) {
              if (!child.matches?.(selector)) continue;
              if (containsInteractive(child) || labelOwnsInteractive(child)) continue;
              const text = usefulPrompt(child.innerText);
              if (text && !genericHeading(text)) return text;
            }
            return '';
          };
          const structuralBoundary = (node) => {
            if (!node) return true;
            if (node.matches?.('section,form')) return true;
            const hint = [node.getAttribute?.('class'), node.getAttribute?.('id')]
              .filter(Boolean).join(' ');
            return /(?:^|[-_\s])(?:questions|questionnaire)(?:$|[-_\s])/i.test(hint);
          };

          // Establish opaque identity before reading ancestor/group semantics. A group may
          // represent one opaque field only when every non-hidden field inside it is the
          // same-name, same-kind radio/checkbox choice. Any text/select/textarea sibling,
          // repeated text field, mixed choice kind, or second opaque name makes the group
          // compound and therefore ineligible to donate prompt text.
          let opaqueName = cleanText(el.getAttribute?.('name'));
          if (!OPAQUE_CARD_RE.test(opaqueName)) opaqueName = '';
          let unsafeOpaqueGroup = false;
          if (!opaqueName && isGroupSubject) {
            const groupFields = Array.from(el.querySelectorAll(FIELD_SELECTOR));
            const opaqueNames = groupFields
              .map((control) => controlName(control))
              .filter((name) => OPAQUE_CARD_RE.test(name));
            const uniqueOpaqueNames = Array.from(new Set(opaqueNames));
            if (uniqueOpaqueNames.length > 0) {
              const candidate = uniqueOpaqueNames.length === 1 ? uniqueOpaqueNames[0] : '';
              const kinds = new Set(groupFields.map((control) => choiceKind(control)).filter(Boolean));
              const ownsOneChoiceField = Boolean(candidate) && kinds.size === 1 &&
                groupFields.length > 0 &&
                groupFields.every((control) =>
                  isChoiceControl(control) && controlName(control) === candidate
                );
              if (ownsOneChoiceField) opaqueName = candidate;
              else unsafeOpaqueGroup = true;
            }
          }

          const ownsOpaqueField = (node) => {
            if (!opaqueName || !node) return false;
            const subjectKind = choiceKind(el);
            const fields = Array.from(node.querySelectorAll(FIELD_SELECTOR));
            return !fields.some((control) => {
              if (control === el) return false;
              const kind = choiceKind(control);
              const sameChoice = Boolean(kind) && controlName(control) === opaqueName &&
                ((isGroupSubject && isChoiceControl(control)) ||
                 (subjectKind && kind === subjectKind));
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
          // use it only after proving that the wrapper owns no foreign field.
          const applicationQuestion = el.closest(
            '.application-question,[data-qa="application-question"],[data-testid="application-question"]'
          );
          if (applicationQuestion && !unsafeOpaqueGroup &&
              (!opaqueName || ownsOpaqueField(applicationQuestion))) {
            let promptText = structuredPrompt(applicationQuestion);
            if (!promptText) {
              for (const child of Array.from(applicationQuestion.children || [])) {
                if (child.contains(el) || containsInteractive(child)) continue;
                promptText = looksLikeUnstructuredPrompt(child, child.innerText);
                if (promptText) break;
              }
            }
            push(promptText);
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
          // climb before structured or unstructured text can be admitted. When the subject
          // itself is a fieldset/radiogroup, inspect that group first so a direct prompt
          // child is retained without climbing into a broader container.
          if (opaqueName) {
            let node = isGroupSubject ? el : el.parentElement;
            for (let depth = 0; node && depth < 6; depth += 1, node = node.parentElement) {
              if (!ownsOpaqueField(node)) break;
              if (node !== el && structuralBoundary(node)) break;

              const promptText = structuredPrompt(node);
              if (promptText) {
                push(promptText);
                break;
              }

              let found = '';
              for (const child of Array.from(node.children || [])) {
                if (child.contains(el) || containsInteractive(child)) continue;
                const text = looksLikeUnstructuredPrompt(child, child.innerText);
                if (text) {
                  found = text;
                  break;
                }
              }
              if (found) {
                push(found);
                break;
              }
            }
          }

          return pieces.join(' | ');
        }"""
    )
    return re.sub(r"\s+", " ", descriptor or "").strip()
