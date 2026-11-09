// Shows a loading message when the form is sent
var form = document.getElementById("compare-form");
if (form) {
  form.addEventListener("submit", function () {
    form.querySelector("button[type=submit]").disabled = true;
    document.getElementById("loading").hidden = false;
  });
}

// Clicking a name in "Recent profiles" fills the first empty box
var nameButtons = document.querySelectorAll(".row-link");
nameButtons.forEach(function (button) {
  button.addEventListener("click", function () {
    var boxA = document.getElementById("a");
    var boxB = document.getElementById("b");
    var box = boxA.value.trim() === "" ? boxA : boxB;
    box.value = button.dataset.fill;
    box.focus();
  });
});
