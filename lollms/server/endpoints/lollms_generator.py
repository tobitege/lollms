"""
project: lollms
file: lollms_generator.py 
author: ParisNeo
description: 
    This module contains a set of FastAPI routes that provide information about the Lord of Large Language and Multimodal Systems (LoLLMs) Web UI
    application. These routes are specific to the generation process

"""

from fastapi import APIRouter, Request, Body
from lollms.server.elf_server import LOLLMSElfServer
from pydantic import BaseModel
from starlette.responses import StreamingResponse
from lollms.types import MSG_TYPE
from lollms.utilities import detect_antiprompt, remove_text_from_string, trace_exception
from ascii_colors import ASCIIColors
import time
import threading
from typing import List, Optional, Union
import random
import string
import json

def _generate_id(length=10):
    letters_and_digits = string.ascii_letters + string.digits
    random_id = ''.join(random.choice(letters_and_digits) for _ in range(length))
    return random_id

class GenerateRequest(BaseModel):
 
    text: str
    n_predict: int = 1024
    stream: bool = False
    temperature: float = 0.4
    top_k: int = 50
    top_p: float = 0.6
    repeat_penalty: float = 1.3
    repeat_last_n: int = 40
    seed: int = -1
    n_threads: int = 1

class V1ChatGenerateRequest(BaseModel):
    """
    Data model for the V1 Chat Generate Request.

    Attributes:
    - model: str representing the model to be used for text generation.
    - messages: list of messages to be used as prompts for text generation.
    - stream: bool indicating whether to stream the generated text or not.
    - temperature: float representing the temperature parameter for text generation.
    - max_tokens: float representing the maximum number of tokens to generate.
    """    
    model: str
    messages: list
    stream: bool
    temperature: float
    max_tokens: float


class V1InstructGenerateRequest(BaseModel):
    """
    Data model for the V1 Chat Generate Request.

    Attributes:
    - model: str representing the model to be used for text generation.
    - messages: list of messages to be used as prompts for text generation.
    - stream: bool indicating whether to stream the generated text or not.
    - temperature: float representing the temperature parameter for text generation.
    - max_tokens: float representing the maximum number of tokens to generate.
    """    
    model: str
    prompt: str
    stream: bool
    temperature: float
    max_tokens: float

# ----------------------- Defining router and main class ------------------------------

router = APIRouter()
elf_server = LOLLMSElfServer.get_instance()


# ----------------------------------- Generation status -----------------------------------------

@router.get("/get_generation_status")
def get_generation_status():
    return {"status":elf_server.busy}


# ----------------------------------- Generation -----------------------------------------
class LollmsGenerateRequest(BaseModel):
    text: str
    model_name: Optional[str] = None
    personality: Optional[int] = None
    n_predict: Optional[int] = 1024
    stream: bool = False
    temperature: float = None
    top_k: Optional[int] = None
    top_p: Optional[float] = None
    repeat_penalty: Optional[float] = None
    repeat_last_n: Optional[int] = None
    seed: Optional[int] = None
    n_threads: Optional[int] = None

@router.post("/lollms_generate")
async def lollms_generate(request: LollmsGenerateRequest):
    """ Endpoint for generating text from prompts using the LoLLMs fastAPI server.

    Args:
    Data model for the Generate Request.
    Attributes:
    - text: str : representing the input text prompt for text generation.
    - model_name: Optional[str] = None : The name of the model to be used (it should be one of the current models)
    - personality_id: Optional[int] = None : The name of the mounted personality to be used (if a personality is None, the endpoint will just return a completion text). To get the list of mounted personalities, just use /list_mounted_personalities
    - n_predict: int representing the number of predictions to generate.
    - stream: bool indicating whether to stream the generated text or not.
    - temperature: float representing the temperature parameter for text generation.
    - top_k: int representing the top_k parameter for text generation.
    - top_p: float representing the top_p parameter for text generation.
    - repeat_penalty: float representing the repeat_penalty parameter for text generation.
    - repeat_last_n: int representing the repeat_last_n parameter for text generation.
    - seed: int representing the seed for text generation.
    - n_threads: int representing the number of threads for text generation.

    Returns:
    - If the elf_server binding is not None:
    - If stream is True, returns a StreamingResponse of generated text chunks.
    - If stream is False, returns the generated text as a string.
    - If the elf_server binding is None, returns None.
    """

    try:
        text = request.text
        n_predict = request.n_predict
        stream = request.stream
        
        if elf_server.binding is not None:
            if stream:

                output = {"text":"","waiting":True,"new":[]}
                def generate_chunks():
                    lk = threading.Lock()

                    def callback(chunk, chunk_type:MSG_TYPE=MSG_TYPE.MSG_TYPE_CHUNK):
                        if elf_server.cancel_gen:
                            return False
                        if chunk is None:
                            return
                        output["text"] += chunk
                        # Yield each chunk of data
                        lk.acquire()
                        try:
                            antiprompt = detect_antiprompt(output["text"])
                            if antiprompt:
                                ASCIIColors.warning(f"\nDetected hallucination with antiprompt: {antiprompt}")
                                output["text"] = remove_text_from_string(output["text"],antiprompt)
                                lk.release()
                                return False
                            else:
                                output["new"].append(chunk)
                                lk.release()
                                return True
                        except Exception as ex:
                            trace_exception(ex)
                            lk.release()
                            return True
                    def chunks_builder():
                        elf_server.binding.generate(
                                                text, 
                                                n_predict, 
                                                callback=callback, 
                                                temperature=request.temperature if request.temperature is not None else elf_server.config.temperature,
                                                top_k=request.top_k if request.top_k is not None else elf_server.config.top_k, 
                                                top_p=request.top_p if request.top_p is not None else elf_server.config.top_p,
                                                repeat_penalty=request.repeat_penalty if request.repeat_penalty is not None else elf_server.config.repeat_penalty,
                                                repeat_last_n=request.repeat_last_n if request.repeat_last_n is not None else elf_server.config.repeat_last_n,
                                                seed=request.seed if request.seed is not None else elf_server.config.seed,
                                                n_threads=request.n_threads if request.n_threads is not None else elf_server.config.n_threads
                                            )
                        output["waiting"] = False
                    thread = threading.Thread(target=chunks_builder)
                    thread.start()
                    current_index = 0
                    while (output["waiting"] and elf_server.cancel_gen == False):
                        while (output["waiting"] and len(output["new"])==0):
                            time.sleep(0.001)
                        lk.acquire()
                        for i in range(len(output["new"])):
                            current_index += 1                        
                            yield output["new"][i]
                        output["new"]=[]
                        lk.release()
                    elf_server.cancel_gen = False

                return StreamingResponse(iter(generate_chunks()))
            else:
                output = {"text":""}
                def callback(chunk, chunk_type:MSG_TYPE=MSG_TYPE.MSG_TYPE_CHUNK):
                    # Yield each chunk of data
                    output["text"] += chunk
                    antiprompt = detect_antiprompt(output["text"])
                    if antiprompt:
                        ASCIIColors.warning(f"\nDetected hallucination with antiprompt: {antiprompt}")
                        output["text"] = remove_text_from_string(output["text"],antiprompt)
                        return False
                    else:
                        return True
                elf_server.binding.generate(
                                                text, 
                                                n_predict, 
                                                callback=callback,
                                                temperature=request.temperature if request.temperature is not None else elf_server.config.temperature,
                                                top_k=request.top_k if request.top_k is not None else elf_server.config.top_k, 
                                                top_p=request.top_p if request.top_p is not None else elf_server.config.top_p,
                                                repeat_penalty=request.repeat_penalty if request.repeat_penalty is not None else elf_server.config.repeat_penalty,
                                                repeat_last_n=request.repeat_last_n if request.repeat_last_n is not None else elf_server.config.repeat_last_n,
                                                seed=request.seed if request.seed is not None else elf_server.config.seed,
                                                n_threads=request.n_threads if request.n_threads is not None else elf_server.config.n_threads
                                            )
                return output["text"]
        else:
            return None
    except Exception as ex:
        trace_exception(ex)
        elf_server.error(ex)
        return {"status":False,"error":str(ex)}

    
# ----------------------- Open AI ----------------------------------------
class Message(BaseModel):
    role: str
    content: str

class Delta(BaseModel):
    content : str = ""
    role : str = "assistant"


class Choices(BaseModel):
    finish_reason: Optional[str] = None,
    index: Optional[int] = 0,
    message: Optional[str] = "",
    logprobs: Optional[float] = None



class Usage(BaseModel):
    prompt_tokens: Optional[int]=0,
    completion_tokens : Optional[int]=0,
    completion_tokens : Optional[int]=0,


class StreamingChoices(BaseModel):
    finish_reason : Optional[str] = "stop"
    index : Optional[int] = 0
    delta : Optional[Delta] = None
    logprobs : Optional[List[float]|None] = None

class StreamingModelResponse(BaseModel):
    id: str
    """A unique identifier for the completion."""

    choices: List[StreamingChoices]
    """The list of completion choices the model generated for the input prompt."""

    created: int
    """The Unix timestamp (in seconds) of when the completion was created."""

    model: Optional[str] = None
    """The model used for completion."""

    object: Optional[str] = "text_completion"
    """The object type, which is always "text_completion" """

    system_fingerprint: Optional[str] = None
    """This fingerprint represents the backend configuration that the model runs with.

    Can be used in conjunction with the `seed` request parameter to understand when
    backend changes have been made that might impact determinism.
    """

    usage: Optional[Usage] = None
    """Usage statistics for the completion request."""

    _hidden_params: dict = {}
    def encode(self, charset):
        encoded = json.dumps(self.dict()).encode(charset)
        return encoded

class ModelResponse(BaseModel):
    id: str
    """A unique identifier for the completion."""

    choices: List[Choices]
    """The list of completion choices the model generated for the input prompt."""

    created: int
    """The Unix timestamp (in seconds) of when the completion was created."""

    model: Optional[str] = None
    """The model used for completion."""

    object: Optional[str] = "text_completion"
    """The object type, which is always "text_completion" """

    system_fingerprint: Optional[str] = None
    """This fingerprint represents the backend configuration that the model runs with.

    Can be used in conjunction with the `seed` request parameter to understand when
    backend changes have been made that might impact determinism.
    """

    usage: Optional[Usage] = None
    """Usage statistics for the completion request."""

    _hidden_params: dict = {}

class GenerationRequest(BaseModel):
    messages: List[Message]
    max_tokens: Optional[int] = 1024
    stream: Optional[bool] = False
    temperature: Optional[float] = 0.1


@router.post("/v1/chat/completions")
async def v1_chat_completions(request: GenerationRequest):
    try:
        messages = request.messages
        text = ""
        for message in messages:
            text += f"{message.role}: {message.content}\n"
        n_predict = request.max_tokens if request.max_tokens>0 else 1024
        stream = request.stream

        if elf_server.binding is not None:
            if stream:
                output = {"text":"","waiting":True,"new":[]}
                def generate_chunks():
                    lk = threading.Lock()

                    def callback(chunk, chunk_type:MSG_TYPE=MSG_TYPE.MSG_TYPE_CHUNK):
                        if elf_server.cancel_gen:
                            return False
                        if chunk is None:
                            return
                        output["text"] += chunk
                        # Yield each chunk of data
                        lk.acquire()
                        try:
                            antiprompt = detect_antiprompt(output["text"])
                            if antiprompt:
                                ASCIIColors.warning(f"\nDetected hallucination with antiprompt: {antiprompt}")
                                output["text"] = remove_text_from_string(output["text"],antiprompt)
                                lk.release()
                                return False
                            else:
                                output["new"].append(chunk)
                                lk.release()
                                return True
                        except Exception as ex:
                            trace_exception(ex)
                            lk.release()
                            return True
                    def chunks_builder():
                        elf_server.binding.generate(
                                                text, 
                                                n_predict, 
                                                callback=callback, 
                                                temperature=request.temperature or elf_server.config.temperature
                                            )
                        output["waiting"] = False
                    thread = threading.Thread(target=chunks_builder)
                    thread.start()
                    current_index = 0
                    while (output["waiting"] and elf_server.cancel_gen == False):
                        while (output["waiting"] and len(output["new"])==0):
                            time.sleep(0.001)
                        lk.acquire()
                        for i in range(len(output["new"])):
                            output_val = StreamingModelResponse(
                                id = _generate_id(), 
                                choices = [StreamingChoices(index= current_index, delta=Delta(content=output["new"][i]))], 
                                created=int(time.time()),
                                model=elf_server.config.model_name,
                                usage=Usage(prompt_tokens= 0, completion_tokens= 10)
                                )
                            current_index += 1                        
                            yield output_val
                        output["new"]=[]
                        lk.release()
                    elf_server.cancel_gen = False

                return StreamingResponse(iter(generate_chunks()))
            else:
                output = {"text":""}
                def callback(chunk, chunk_type:MSG_TYPE=MSG_TYPE.MSG_TYPE_CHUNK):
                    # Yield each chunk of data
                    if chunk is None:
                        return
                    output["text"] += chunk
                    antiprompt = detect_antiprompt(output["text"])
                    if antiprompt:
                        ASCIIColors.warning(f"\nDetected hallucination with antiprompt: {antiprompt}")
                        output["text"] = remove_text_from_string(output["text"],antiprompt)
                        return False
                    else:
                        return True
                elf_server.binding.generate(
                                                text, 
                                                n_predict, 
                                                callback=callback,
                                                temperature=request.temperature or elf_server.config.temperature
                                            )
                return ModelResponse(id = _generate_id(), choices = [Choices(message=output["text"])], created=int(time.time()))
        else:
            return None
    except Exception as ex:
        trace_exception(ex)
        elf_server.error(ex)
        return {"status":False,"error":str(ex)}


@router.post("/v1/completions")
async def v1_completion(request: Request):
    """
    Executes Python code and returns the output.

    :param request: The HTTP request object.
    :return: A JSON response with the status of the operation.
    """

    try:
        data = (await request.json())
        text = data.get("prompt")
        n_predict = data.get("max_tokens")
        stream = data.get("stream")
        
        if elf_server.binding is not None:
            if stream:
                output = {"text":""}
                def generate_chunks():
                    def callback(chunk, chunk_type:MSG_TYPE=MSG_TYPE.MSG_TYPE_CHUNK):
                        # Yield each chunk of data
                        output["text"] += chunk
                        antiprompt = detect_antiprompt(output["text"])
                        if antiprompt:
                            ASCIIColors.warning(f"\nDetected hallucination with antiprompt: {antiprompt}")
                            output["text"] = remove_text_from_string(output["text"],antiprompt)
                            return False
                        else:
                            yield chunk
                            return True
                    return iter(elf_server.binding.generate(
                                                text, 
                                                n_predict, 
                                                callback=callback, 
                                                temperature=data.get("temperature", elf_server.config.temperature)
                                            ))
                
                return StreamingResponse(generate_chunks())
            else:
                output = {"text":""}
                def callback(chunk, chunk_type:MSG_TYPE=MSG_TYPE.MSG_TYPE_CHUNK):
                    # Yield each chunk of data
                    output["text"] += chunk
                    antiprompt = detect_antiprompt(output["text"])
                    if antiprompt:
                        ASCIIColors.warning(f"\nDetected hallucination with antiprompt: {antiprompt}")
                        output["text"] = remove_text_from_string(output["text"],antiprompt)
                        return False
                    else:
                        return True
                elf_server.binding.generate(
                                                text, 
                                                n_predict, 
                                                callback=callback,
                                                temperature=data.get("temperature", elf_server.config.temperature)
                                            )
                return output["text"]
        else:
            return None
    except Exception as ex:
        trace_exception(ex)
        elf_server.error(ex)
        return {"status":False,"error":str(ex)}


@router.post("/stop_gen")
def stop_gen():
    elf_server.cancel_gen = True
    return {"status": True} 