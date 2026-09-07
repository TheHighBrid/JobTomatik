import re


async def element_descriptor(page, element) -> str:
    descriptor = await element.evaluate(
        """(el) => {
          const pieces = [];
          const push = (value) => {
            const clean = String(value || '').replace(/\\s+/g, ' ').trim();
            if (clean && !pieces.includes(clean)) pieces.push(clean);
          };
          ['name','id','placeholder','aria-label','autocomplete',
           'data-testid','data-qa','data-automation-id'].forEach(
            (name) => push(el.getAttribute(name))
          );
          if (el.labels) Array.from(el.labels).forEach((label) => push(label.innerText));
          (el.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean)
            .forEach((id) => push(document.getElementById(id)?.innerText));
          (el.getAttribute('aria-describedby') || '').split(/\\s+/).filter(Boolean)
            .forEach((id) => push(document.getElementById(id)?.innerText));

          // Lever hosted forms wrap each employer-authored custom field in an
          // .application-question container, but the radio/checkbox inputs often
          // have no fieldset, legend, aria-label, or labelledby relationship. In
          // that shape, the input's own descriptor collapses to an opaque name
          // such as cards[uuid][field0] plus the selected option label. Preserve
          // the nearest question prompt so the policy classifier sees the human
          // meaning of the control rather than an implementation identifier.
          const applicationQuestion = el.closest('.application-question');
          if (applicationQuestion) {
            const directPrompt = applicationQuestion.querySelector(':scope > label, :scope > legend');
            push(directPrompt?.innerText);
            Array.from(applicationQuestion.children || []).forEach((child) => {
              if (child === directPrompt || child.contains(el)) return;
              if (child.querySelector('input,select,textarea,button,[role="radio"],[role="checkbox"],[role="combobox"]')) return;
              const text = String(child.innerText || '').replace(/\\s+/g, ' ').trim();
              if (text && text.length <= 500) push(text);
            });
          }

          const group = el.closest('fieldset,[role="radiogroup"],[role="group"]');
          if (group) {
            push(group.getAttribute('aria-label'));
            push(group.querySelector(':scope > legend')?.innerText);
          }
          push(el.closest('label')?.innerText);
          return pieces.join(' | ');
        }"""
    )
    return re.sub(r"\s+", " ", descriptor or "").strip()
