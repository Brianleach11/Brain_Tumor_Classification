import streamlit as st
import tensorflow as tf
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing import image
import numpy as np
import plotly.graph_objects as go
import cv2
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Dropout, Flatten
from tensorflow.keras.optimizers import Adamax
from tensorflow.keras.metrics import Precision, Recall
import google.generativeai as genai
import PIL.Image
import os
from dotenv import load_dotenv
import gdown
load_dotenv()

if "GOOGLE_API_KEY" in os.environ:
    api_key = os.environ.get("GOOGLE_API_KEY")
else:
    api_key = st.secrets["GOOGLE_API_KEY"]
genai.configure(api_key=api_key)

output_dir = 'saliency_maps'
os.makedirs(output_dir, exist_ok=True)

def generate_explanation(img_path, model_prediction, confidence):
    prompt = f"""You are an expert neurologist. You are teasked with explaining a saliency map of a brain tumor MRI scan.
    The saliency map was generated by a deep learning model that was trained to classify brain tumors
    as either glioma, meningioma, no tumor, or pituitary.

    The saliency map highlights the regions of the image that the machine learning model is focusing on to make the prediction.

    The deep learning model predicted the image to be of class '{model_prediction}' with a confidence of  {confidence * 100:.2f}%.

    In your response: 
    - Use specific expert medical terminology.
    - Explain what regions of the brain the model is focusing on, based on the saliency map. Refer to the regions highlighted
    in light cyan, those are the regions where the model is focusing on.
    - Explain possible reasons why the model made the predicition it did.
    - Don't mention anything like 'The saliency map highlights the regions the model is focusing on, which are in light cyan' 
    in your explanation.
    - Keep your explanation to 10 sentences max.

    Let's thinkg step by step about this. Verify step by step that your explanation is correct.
    """
    img = PIL.Image.open(img_path)
    model = genai.GenerativeModel(model_name='gemini-1.5-flash-latest')
    response = model.generate_content([prompt, img])

    return response.text

def generate_saliency_map(model, img_array, class_index, img_size):
    with tf.GradientTape() as tape:
        img_tensor = tf.convert_to_tensor(img_array)
        tape.watch(img_array)
        predictions = model(img_array)
        target_class = predictions[:, class_index]


    gradients = tape.gradient(target_class, img_tensor)
    gradients = tf.math.abs(gradients)
    gradients = tf.reduce_max(gradients, axis=-1)
    gradients = gradients.numpy().squeeze()

    gradients = cv2.resize(gradients, img_size)

    center = (gradients.shape[0]//2, gradients.shape[1]//2)
    radius = min(center[0], center[1]) - 10
    y,x = np.ogrid[:gradients.shape[0], :gradients.shape[1]]
    mask = (x - center[0])**2 + (y - center[1])**2 <= radius**2

    gradients = gradients * mask

    brain_gradients = gradients[mask]
    if brain_gradients.max() > brain_gradients.min():
        brain_gradients = (brain_gradients - brain_gradients.min()) / (brain_gradients.max() - brain_gradients.min())

    gradients[mask] = brain_gradients

    threshold = np.percentile(gradients[mask], 80)
    gradients[gradients < threshold] = 0

    gradients = cv2.GaussianBlur(gradients, (11,11), 0)

    heatmap = cv2.applyColorMap(np.uint8(255*gradients), cv2.COLORMAP_JET)
    heatmap = cv2.cvtColor(heatmap, cv2.COLOR_BGR2RGB)
    heatmap = cv2.resize(heatmap, img_size)

    original_img = image.image_to_array(img)
    superimposed_img = heatmap * 0.7 + original_img * 0.3
    superimposed_img = superimposed_img.astype(np.uint8)

    img_path = os.path.join(output_dir, uploaded_file.name)
    with open(img_path, 'wb') as f:
        f.write(uploaded_file.getbuffer())

    saliency_map_path = f'saliency_maps/{uploaded_file.name}'

    cv2.imwrite(saliency_map_path, cv2.cvtColor(superimposed_img, cv2.COLOR_RGB2BGR))
    return superimposed_img

def load_xception_model(model_path):
    img_shape = (299,299,3)
    base_model = tf.keras.applications.Xception(input_shape=img_shape,
                                               include_top=False,
                                               weights='imagenet',
                                               pooling='max')
    model = Sequential([
        base_model,
        Flatten(),
        Dropout(rate=0.3),
        Dense(128, activation='relu'),
        Dropout(rate=0.25),
        Dense(4, activation='softmax')
    ])
    model.build((None,)+img_shape)
    model.compile(Adamax(learning_rate=0.001), 
                  loss='categorical_crossentropy', 
                  metrics=['accuracy', Precision(), Recall()])
    model.load_weights(model_path)
    return model

def generate_confidence_graph(predictions):
    # Create labels and values for the graph
    labels = ['Glioma', 'Meningioma', 'No Tumor', 'Pituitary']
    values = predictions * 100  # Convert to percentages
    
    # Create a bar graph using plotly
    fig = go.Figure(data=[
        go.Bar(
            x=labels,
            y=values,
            text=[f'{v:.1f}%' for v in values],  # Add percentage labels on bars
            textposition='auto',
            marker_color=['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728']  # Custom colors for each class
        )
    ])
    
    # Update layout for better visualization
    fig.update_layout(
        title='Prediction Confidence by Class',
        yaxis_title='Confidence (%)',
        yaxis_range=[0, 100],  # Set y-axis range from 0 to 100%
        plot_bgcolor='white',
        showlegend=False
    )
    
    # Add grid lines for better readability
    fig.update_yaxes(gridcolor='lightgrey', gridwidth=0.5)
    
    # Convert to image for Streamlit
    return fig

def download_models():
    # Create a models directory in the Streamlit environment
    os.makedirs('models', exist_ok=True)
    
    cnn_id = "1x9t4iiOryE2jNJ8OCcWgkbNe17YXlPnU"
    xception_id = "10tcxflFgOtgrTXDR_fMj_3Dr4oM_rbsm"
    
    cnn_path = 'models/cnn_model.h5'
    xception_path = 'models/xception_model.weights.h5'
    
    if not os.path.exists(cnn_path):
        with st.spinner('Downloading CNN model...'):
            url = f"https://drive.google.com/uc?id={cnn_id}"
            gdown.download(url, cnn_path, quiet=False)
    
    if not os.path.exists(xception_path):
        with st.spinner('Downloading Xception model...'):
            url = f"https://drive.google.com/uc?id={xception_id}"
            gdown.download(url, xception_path, quiet=False)
            
    return cnn_path, xception_path

# Streamlit UI
st.title("Brain Tumor Classification")
st.write("Upload an MRI scan to classify whether it contains a brain tumor.")
cnn_path, xception_path = download_models()
uploaded_file = st.file_uploader("Choose an MRI scan...", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:

    selected_model = st.radio(
        "Select a model:", 
        ("Transfer Learning - Xception", "Custom CNN")
    )
    
    if selected_model == "Transfer Learning - Xception":
        model = load_xception_model(xception_path)
        img_size = (299,299)
    else:
        model = load_model(cnn_path)
        img_size = (224,224)

    labels = ['Glioma', 'Meningioma', 'No Tumor', 'Pituitary']

    # Preprocess the image
    img = image.load_img(uploaded_file, target_size=img_size)
    img_array = image.img_to_array(img)
    img_array = np.expand_dims(img_array, axis=0)
    img_array /= 255.0

    prediction = model.predict(img_array)

    class_index = np.argmax(prediction[0])
    result = labels[class_index]

    st.write(f"Predicted Class: {result}")
    st.write("Predictions:")
    for label, prob in zip(labels, prediction[0]):
        st.write(f"{label}: {prob:.4f}")

    saliency_map = generate_saliency_map(model, img_array, class_index, img_size)

    col1, col2 = st.columns(2)
    with col1:
        st.image(uploaded_file, caption='Uploaded Image', use_column_width=True)
    with col2:
        st.image(saliency_map, caption='Saliency Map', use_column_width=True)

    confidence_graph = generate_confidence_graph(prediction[0])
    st.plotly_chart(confidence_graph, use_container_width=True)

    saliency_map_path = f'saliency_maps/{uploaded_file.name}'
    explanation = generate_explanation(saliency_map_path, result, prediction[0][class_index])
    st.write("## Explanation:")
    st.write(explanation)
