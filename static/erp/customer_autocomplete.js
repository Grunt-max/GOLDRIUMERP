document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('input[list]').forEach(input => {
    const listId = input.getAttribute('list') || '';
    if (!listId.includes('customer-suggestions')) return;

    const datalist = document.getElementById(listId);
    if (!datalist || datalist.dataset.minLengthReady) return;
    datalist.dataset.minLengthReady = '1';

    const choices = Array.from(datalist.options).map(option => ({
      value: option.value,
      id: option.dataset.id || '',
    }));
    const linkedInputs = Array.from(document.querySelectorAll('input[list]'))
      .filter(candidate => candidate.getAttribute('list') === listId);

    const update = source => {
      const keyword = source.value.trim().toLocaleLowerCase('ko-KR');
      datalist.replaceChildren();
      if (keyword.length < 2) return;

      choices
        .filter(choice => choice.value.toLocaleLowerCase('ko-KR').includes(keyword))
        .slice(0, 30)
        .forEach(choice => {
          const option = document.createElement('option');
          option.value = choice.value;
          if (choice.id) option.dataset.id = choice.id;
          datalist.appendChild(option);
        });
    };

    linkedInputs.forEach(linkedInput => {
      linkedInput.placeholder = '거래처명 2글자 이상 입력';
      linkedInput.addEventListener('input', () => update(linkedInput));
      linkedInput.addEventListener('focus', () => update(linkedInput));
    });
    datalist.replaceChildren();
  });
});
