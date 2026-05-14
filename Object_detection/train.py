from ultralytics import YOLO

def train_model():
    # Load a pretrained YOLOv8 model
    # You can change 'yolov8n.pt' to 'yolov8s.pt', 'yolov8m.pt', etc. depending on your needs
    model = YOLO('yolov8n.pt')

    # Train the model
    # Change 'data.yaml' to the path of your dataset configuration file
    # Adjust epochs, imgsz, and batch size according to your hardware capabilities
    results = model.train(
        data='data.yaml',   # Path to your dataset YAML file
        epochs=100,         # Number of training epochs
        imgsz=640,          # Image size
        batch=16,           # Batch size
        device='0',         # GPU device, e.g., '0' or '0,1,2,3' or 'cpu'
        name='yolov8_custom_model' # Directory name to save training results
    )
    
    print(f"Training completed. Best model saved to: {results.save_dir}/weights/best.pt")

if __name__ == '__main__':
    train_model()
