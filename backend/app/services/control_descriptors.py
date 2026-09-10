import re


async def element_descriptor(page, element) -> str:
    descriptor = await element.evaluate(
        r"""(el) => {
          const pieces = [];
          const INTERACTIVE_SELECTOR =
            'input,select,textarea,button,[role="radio"],[role="checkbox"],[role="combobox"]';
          const FIELD_SELECTOR = 'input:not([type="hidden"]),select,textarea';
          const OPAQUE_CARD_RE = /^cards\[[^\]]+\]\[field\d+\]$/i;
          const push = (value) => {
            const clean = String(value || '').replace(/\s+/g, ' ').trim();
            if (clean && !pieces.includes(clean)) pieces.push(clean);
          };
          const cleanText = (value) => String(value || '').replace(/\s+/g, ' ').trim();
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
              if (containsInteractive(child)) continue;
              const text = usefulPrompt(child.innerText);
              if (text && !genericHeading(text)) return text;
            }
            return '';
          };

          ['name','id','placeholder','aria-label','autocomplete',
           'data-testid','data-qa','data-automation-id'].forEach(
            (name) => push(el.getAttribute(name))
          );
          if (el.labels) Array.from(el.labels).forEach((label) => push(label.innerText));
          (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean)
            .forEach((id) => push(document.getElementById(id)?.innerText));
          (el.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean)
            .forEach((id) => push(document.getElementById(id)?.innerText));

          // Only bind known per-question wrappers. Do not use substring class matches:
          // plural/compound section wrappers can span multiple questions and must not
          // leak one question's text into another control's descriptor.
          const applicationQuestion = el.closest(
            '.application-question,[data-qa="application-question"],[data-testid="application-question"]'
          );
          if (applicationQuestion) {
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

          const group = el.closest('fieldset,[role="radiogroup"],[role="group"]');
          if (group) {
            push(group.getAttribute('aria-label'));
            push(group.querySelector(':scope > legend')?.innerText);
          }
          push(el.closest('label')?.innerText);

          // Usually the opaque identity belongs to the control itself. Native choice
          // handlers may instead ask for a fieldset/radiogroup descriptor, so derive the
          // identity only when that group contains exactly one opaque card field name.
          let opaqueName = cleanText(el.getAttribute('name'));
          if (!OPAQUE_CARD_RE.test(opaqueName)) opaqueName = '';
          if (!opaqueName && el.matches?.('fieldset,[role="radiogroup"],[role="group"]')) {
            const groupOpaqueNames = Array.from(el.querySelectorAll(FIELD_SELECTOR))
              .map((control) => cleanText(control.getAttribute('name')))
              .filter((name) => OPAQUE_CARD_RE.test(name));
            const uniqueOpaqueNames = Array.from(new Set(groupOpaqueNames));
            if (uniqueOpaqueNames.length === 1) {
              opaqueName = uniqueOpaqueNames[0];
              push(opaqueName);
            }
          }

          // Current Lever card controls can expose only cards[uuid][fieldN] while the
          // employer prompt lives in a nearby wrapper. Recover context only inside the
          // local field. Any other non-hidden form field is an ownership boundary, even
          // when that sibling uses a conventional name rather than cards[...]. Same-name
          // radio/checkbox choices are allowed because they belong to the same question.
          if (opaqueName) {
            let node = el.parentElement;
            for (let depth = 0; node && depth < 6; depth += 1, node = node.parentElement) {
              const fields = Array.from(node.querySelectorAll(FIELD_SELECTOR));
              const hasForeignField = fields.some((control) => {
                const name = cleanText(control.getAttribute('name'));
                return name !== opaqueName;
              });

              // A distinct field means this ancestor is a multi-field container. Never
              // inspect its labels or siblings, because doing so could attach a legal or
              // sensitive prompt from a neighboring control to this opaque field.
              if (hasForeignField) break;

              const promptText = structuredPrompt(node);
              if (promptText) {
                push(promptText);
                break;
              }

              // Section/form containers are structural boundaries. A plain heading in one
              // of these containers is not enough evidence to bind a prompt to the control.
              if (node.matches?.('section,form')) break;
              const boundaryHint = [node.getAttribute?.('class'), node.getAttribute?.('id')]
                .filter(Boolean).join(' ');
              if (/(?:^|[-_\s])(?:questions|questionnaire)(?:$|[-_\s])/i.test(boundaryHint)) break;

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
