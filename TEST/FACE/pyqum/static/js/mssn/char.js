//when page is loading:
$(document).ready(function(){
    $('div.charcontent').hide();

    return false;
});

// RETURN to Sample selection page:
$('input.char.loaded#sample-name').on('click', function() {
    window.location.href='/auth/user';
    return false;
});


 
