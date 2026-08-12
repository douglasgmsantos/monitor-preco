// Configuração PÚBLICA do Firebase — cópia de publico/firebase-config.js.
//
// Isto não é segredo. A apiKey identifica o projeto, não autoriza nada — a
// proteção real são as security rules em firestore.rules. Não tente ofuscar.
import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";
import { getFirestore } from "firebase/firestore";

export const configFirebase = {
  apiKey: "AIzaSyCi5GXgoFOGJycaISTgKmo0vkhmLjclq3E",
  authDomain: "report-price.firebaseapp.com",
  projectId: "report-price",
  storageBucket: "report-price.firebasestorage.app",
  messagingSenderId: "412325530305",
  appId: "1:412325530305:web:4ee0088c303eabb5372240",
};

const app = initializeApp(configFirebase);
export const auth = getAuth(app);
export const db = getFirestore(app);
