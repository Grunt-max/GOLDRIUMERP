document.addEventListener('DOMContentLoaded', () => {
  const selector = 'input[type="file"][name="images"],input[type="file"][name="order_image"]';

  document.querySelectorAll(selector).forEach(input => {
    if (input.dataset.mediaReady) return;
    input.dataset.mediaReady = '1';
    input.classList.add('media-source-input');
    input.setAttribute('accept', 'image/*');
    input.removeAttribute('capture');

    const picker = document.createElement('div');
    picker.className = 'media-picker';
    const cameraButton = document.createElement('button');
    cameraButton.type = 'button';
    cameraButton.className = 'media-camera-button';
    cameraButton.textContent = '📷 카메라 촬영';
    const galleryButton = document.createElement('button');
    galleryButton.type = 'button';
    galleryButton.className = 'media-gallery-button';
    galleryButton.textContent = '▧ 갤러리 선택';
    const status = document.createElement('small');
    status.className = 'media-picker-status';

    const update = () => {
      const files = Array.from(input.files || []);
      status.textContent = files.length
        ? `사진 ${files.length}개 선택됨: ${files.map(file => file.name).join(', ')}`
        : '선택된 사진 없음';
      picker.classList.toggle('has-files', files.length > 0);
    };

    const openInput = capture => {
      if (capture) input.setAttribute('capture', 'environment');
      else input.removeAttribute('capture');
      if (typeof input.showPicker === 'function') input.showPicker();
      else input.click();
    };

    cameraButton.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      openInput(true);
    });
    galleryButton.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      openInput(false);
    });

    input.addEventListener('change', update);
    picker.append(cameraButton, galleryButton, status);

    // The input is rendered inside a label. Buttons inside that label can
    // reopen the chooser and discard a selection on Android browsers.
    const label = input.closest('label');
    if (label && label.parentNode) label.insertAdjacentElement('afterend', picker);
    else input.insertAdjacentElement('afterend', picker);
    update();
  });
});
