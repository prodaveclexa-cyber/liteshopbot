const tg = window.Telegram.WebApp;

tg.ready();
tg.expand();

function addToCart(name, price) {
  const data = {
    action: "add_to_cart",
    product: name,
    price: price
  };

  tg.sendData(JSON.stringify(data));
}