"use client";

import Image from "next/image";
import { getLinkToken, exchangePublicToken } from "@services";
import { Button } from "@mui/material";
import { use, useState, useEffect } from "react";
import { usePlaidLink, PlaidLinkOptions,  } from "react-plaid-link";


export default function Home() {
  const [linkToken, setLinkToken] = useState<string | null>(null);

  const handleClick = () => {
    getLinkToken().then((linkToken) => {
      console.log(linkToken);
      setLinkToken(linkToken);
    });
  }

  const onSuccess = (public_token: string, metadata: object) => {
    console.log(public_token);
    console.log(metadata);
    exchangePublicToken(public_token).then((data) => {
      console.log(data);
    });
  }

  const config: PlaidLinkOptions = {
    token: linkToken!,
    onSuccess: onSuccess,
  };

  const { open, ready } = usePlaidLink(config);

  useEffect(() => {
    if (ready) {
      open();
    }
  }, [ready, open]);

  return (
    <Button onClick={handleClick}> Finance App </Button>
  );
}
