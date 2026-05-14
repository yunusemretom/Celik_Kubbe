import cv2
from ultralytics import YOLO

def run_realtime_detection(model_path, source=0):
    """
    Run real-time object detection using YOLOv8.
    
    Args:
        model_path (str): Path to the YOLO model (e.g., 'yolov8n.pt' or 'yolov8n.engine').
        source (int or str): Video source. 0 for webcam, or a path to a video file / RTSP stream.
    """
    print(f"Loading model: {model_path}")
    # Load the model. Ultralytics automatically handles both PyTorch (.pt) and TensorRT (.engine) formats.
    model = YOLO(model_path)

    # Open the video source
    cap = cv2.VideoCapture(source)

    if not cap.isOpened():
        print(f"Error: Could not open video source {source}")
        return

    print("Starting real-time inference. Press 'q' to quit.")

    while True:
        success, frame = cap.read()
        
        if not success:
            print("Failed to read frame from video source. Exiting...")
            break

        # Run inference on the current frame
        # We can adjust confidence threshold (conf) or IoU threshold (iou) here
        results = model(frame, conf=0.5, verbose=False)

        # Plot the predictions on the frame
        annotated_frame = results[0].plot()

        # Display the frame
        cv2.imshow("YOLO Real-Time Detection", annotated_frame)

        # Break the loop if 'q' is pressed
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # Release resources
    cap.release()
    cv2.destroyAllWindows()

if __name__ == '__main__':
    # You can change this to your trained model path or the exported .engine file.
    # E.g., MODEL_PATH = 'yolov8n.engine' for TensorRT inference.
    MODEL_PATH = 'yolov8n.pt' 
    
    # 0 is usually the default built-in webcam.
    # You can also put an RTSP link like 'rtsp://192.168.1.x:554/stream'
    VIDEO_SOURCE = 0 
    
    run_realtime_detection(MODEL_PATH, VIDEO_SOURCE)
