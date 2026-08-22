document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('input[type="file"][name="images"],input[type="file"][name="order_image"]').forEach(gallery=>{
    if(gallery.dataset.mediaReady)return;
    gallery.dataset.mediaReady='1';
    gallery.classList.add('media-source-input');
    gallery.setAttribute('accept','image/*');
    const camera=gallery.cloneNode(false);
    camera.removeAttribute('id');
    camera.removeAttribute('multiple');
    camera.setAttribute('capture','environment');
    camera.dataset.mediaReady='1';
    const picker=document.createElement('div');picker.className='media-picker';
    const cameraButton=document.createElement('button');cameraButton.type='button';cameraButton.className='media-camera-button';cameraButton.textContent='📷 카메라 촬영';
    const galleryButton=document.createElement('button');galleryButton.type='button';galleryButton.className='media-gallery-button';galleryButton.textContent='▧ 갤러리 선택';
    const status=document.createElement('small');status.className='media-picker-status';status.textContent='선택된 사진 없음';
    const update=()=>{const count=(camera.files?.length||0)+(gallery.files?.length||0);status.textContent=count?`사진 ${count}개 선택됨`:'선택된 사진 없음'};
    cameraButton.addEventListener('click',event=>{event.preventDefault();camera.click()});
    galleryButton.addEventListener('click',event=>{event.preventDefault();gallery.click()});
    camera.addEventListener('change',update);gallery.addEventListener('change',update);
    gallery.insertAdjacentElement('afterend',camera);camera.insertAdjacentElement('afterend',picker);
    picker.append(cameraButton,galleryButton,status);
  });
});
