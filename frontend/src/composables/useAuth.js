import { ref } from "vue";
import {
  onAuthStateChanged, signInWithEmailAndPassword, createUserWithEmailAndPassword,
  GoogleAuthProvider, signInWithPopup, signOut,
} from "firebase/auth";
import { auth } from "../firebase.js";

const usuario = ref(null);
const carregouAuth = ref(false);

onAuthStateChanged(auth, (quem) => {
  usuario.value = quem;
  carregouAuth.value = true;
});

function traduzir(erro) {
  const codigo = (erro && erro.code) || "";
  const mapa = {
    "auth/invalid-credential": "E-mail ou senha incorretos.",
    "auth/invalid-email": "E-mail inválido.",
    "auth/weak-password": "A senha precisa de ao menos 6 caracteres.",
    "auth/email-already-in-use": "Esse e-mail já tem conta. Use Entrar.",
    "auth/popup-closed-by-user": "Janela do Google fechada antes de concluir.",
    "auth/operation-not-allowed": "Provedor não habilitado no Firebase Console.",
  };
  return mapa[codigo] || `Falha ao autenticar (${codigo || erro})`;
}

export function useAuth() {
  return {
    usuario,
    carregouAuth,
    entrar: (email, senha) => signInWithEmailAndPassword(auth, email.trim(), senha),
    criarConta: (email, senha) => createUserWithEmailAndPassword(auth, email.trim(), senha),
    entrarComGoogle: () => signInWithPopup(auth, new GoogleAuthProvider()),
    sair: () => signOut(auth),
    traduzir,
  };
}
