(function () {
  let ultimaSenhaExibida = null;

  const verificarPedidosProntos = async () => {
    try {
      const response = await fetch(
        "/api/v1/monitor/pedidos/?t=" + new Date().getTime(),
        {
          cache: "no-store",
        },
      );
      const data = await response.json();
      console.log("Dados recebidos da API:", data); // Log para depuração
      // Se a lista não estiver vazia, pegamos o primeiro item (que é o mais recente)
      if (data.chamados && data.chamados.length > 0) {
        const ultimoPedido = data.chamados[0];

        if (String(ultimoPedido.id) !== String(ultimaSenhaExibida)) {
          const display = document.getElementById("display-senha");
          if (display) display.innerText = `#${ultimoPedido.senha}`;

          ultimaSenhaExibida = ultimoPedido.id;
          console.log("Senha atualizada para:", ultimoPedido.senha);
        }
      }
    } catch (error) {
      console.error("Erro na busca:", error);
    }
  };

  // setInterval(verificarPedidosProntos, 3000);
    // Executa imediatamente ao carregar
  verificarPedidosProntos();

  // Executa a cada 3 segundos
  setInterval(verificarPedidosProntos, 3000);

  // Recarrega a pagina automaticamente a cada 5 segundos com cache-buster
  setInterval(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("_reload", Date.now().toString());
    window.location.replace(url.toString());
  }, 5000);
})();
