from ultralytics import YOLO

def export_to_tensorrt():
    # Load the trained YOLOv8 model
    # Replace 'runs/detect/yolov8_custom_model/weights/best.pt' with the path to your trained model
    model = YOLO('yolov8n.pt') 

    # Export the model to TensorRT format (.engine)
    # Ensure that you have TensorRT installed and configured on your system
    # This process might take a while depending on your hardware
    # The half=True argument enables FP16 precision, which makes inference faster but might slightly reduce accuracy
    print("Exporting model to TensorRT engine...")
    engine_path = model.export(
        format='engine', 
        device='0',      # Specify the GPU to use for export
        half=True,       # Use FP16 precision
        dynamic=False    # Set to True if you need dynamic batch sizes
    )
    
    print(f"Export completed. TensorRT engine saved to: {engine_path}")

if __name__ == '__main__':
    export_to_tensorrt()
